import io
import logging
import os
import tempfile
from dataclasses import dataclass
from typing import List, Optional

from google.cloud import storage
from jinja2 import Template

import util
from exchangelib import (Account, Build, Configuration, Credentials,
                         FaultTolerance, FileAttachment, HTMLBody, Mailbox,
                         Message, Version)
from pikepdf import Pdf
from PyPDF2 import PdfFileReader, PdfFileWriter

logging.getLogger("exchangelib").setLevel(logging.ERROR)
logging.basicConfig(level=logging.INFO)


@dataclass
class Attachment:
    mimetype: str
    bucket: str
    file_name: str
    full_path: str
    content: Optional[bytes]


@dataclass
class Email:
    sent_on: str
    received_on: str
    sender: str
    recipient: str
    subject: str or None
    body: str or None
    attachments: List[Attachment]


@dataclass
class EWSConfig:
    email_account: str
    password: str
    mail_from: str
    mail_to_mapping: str
    hardcoded_recipients: bool
    needs_pdfs: bool
    pdf_only: bool
    merge_pdfs: bool
    send_replies: bool
    exchange_version: dict
    exchange_url: str
    reply_to_email: str
    ignore_reply_subjects: List[str]
    ignore_reply_senders: List[str]


class MailProcessor:
    def __init__(self, email: Email, config: EWSConfig):
        self._email = email
        self._config = config
        self._gcs_client = storage.Client()
        credentials = Credentials(config.email_account, config.password)
        version = Version(
            build=Build(
                config.exchange_version["major"], config.exchange_version["minor"]
            )
        )
        ews_config = Configuration(
            service_endpoint=config.exchange_url,
            credentials=credentials,
            auth_type="basic",
            version=version,
            retry_policy=FaultTolerance(max_wait=300),
        )
        self._account = Account(
            primary_smtp_address=config.email_account,
            config=ews_config,
            autodiscover=False,
            access_type="delegate",
        )

        # Setup reply-mail client.

        recipient = ""
        if self._config.hardcoded_recipients:
            recipient = self._config.mail_to_mapping.get(self._email.recipient)
        else:
            recipient = self._config.mail_to_mapping.get("STANDARD")
        acc_credentials = Credentials(
            username=recipient["sender_account"],
            password=util.get_secret(
                os.environ["PROJECT_ID"], recipient["sender_account_secret"]
            ),
        )
        acc_config = Configuration(
            service_endpoint=config.exchange_url,
            credentials=acc_credentials,
            auth_type="basic",
            version=version,
            retry_policy=FaultTolerance(max_wait=300),
        )
        self._reply_email_account = Account(
            primary_smtp_address=recipient["sender_account"],
            config=acc_config,
            autodiscover=False,
            access_type="delegate",
        )

    def process(self):
        """
        Sends an e-mail as "me" using the mail service and message body.
        """
        pdf_count = self._load_attachments()

        # Get recipient based on recipient config
        recipient = self._config.mail_to_mapping.get(self._email.recipient)
        # If no recipient can be found
        if not recipient:
            # Check if STANDARD recipient is found
            recipient = self._config.mail_to_mapping.get("STANDARD")
            if not recipient:
                logging.error("Recipient could not be found in config")
                return False
            else:
                recipient = self._email.recipient
        else:
            recipient = self._config.mail_to_mapping.get(self._email.recipient)[
                "recipient_email"
            ]

        if self._config.needs_pdfs:
            if pdf_count > 0:
                self._send_email(
                    self._account,
                    self._email.subject,
                    self._email.body,
                    [recipient],
                    self._email.attachments,
                )
        else:
            self._send_email(
                self._account,
                self._email.subject,
                self._email.body,
                [recipient],
                self._email.attachments,
            )

        try:
            if self._config.send_replies:
                if pdf_count == 0:
                    self._send_reply_email("templates/error.html")
                elif pdf_count == 1:
                    self._send_reply_email("templates/success.html")
                else:
                    self._send_reply_email("templates/warning.html")
        except:  # noqa: E722
            logging.warning("Error sending reply email", exc_info=True)
        return True

    def _load_attachments(self):
        """
        Downloads attachments from a gcs bucket.
        Filters and merges pdf attachments if applicable.
        Returns the number of pdf's in the email.
        """

        pdf_list = [a for a in self._email.attachments if a.mimetype.endswith("pdf")]
        pdf_count = len(pdf_list)

        if self._config.pdf_only:
            self._email.attachments = pdf_list

        for attachment in self._email.attachments:
            attachment.content = self._read_gcs(attachment.bucket, attachment.full_path)

            logging.info(f"Downloaded attachment {attachment.file_name}")

        if self._email.attachments and self._config.merge_pdfs:
            first_attachment = next(iter(self._email.attachments))
            attachment_name = first_attachment.file_name
            self._merge_pdfs(attachment_name)

        return pdf_count

    def _merge_pdfs(self, attachment_name: str):
        """
        Merges pdf attachments to a single file.
        This function uses both pikePDF (For merging), and pyPDF2 (for cleaning).
        An initial implementation used only pyPDF2, but that proved to problematic since pyPDF
        has quite a lot of trouble merging different types of PDFs. Since pikePDF doesn't feature sanitizing pdfs,
        we run it through pikepdf afterwards.
        """

        attachments = self._email.attachments
        self._email.attachments = [
            a for a in attachments if not a.mimetype.endswith("pdf")
        ]

        # Go through all attachments and merge them using pikePDF
        merged_pdf = Pdf.new()
        version = merged_pdf.pdf_version

        for attachment in attachments:
            with io.BytesIO(attachment.content) as file:
                src_pdf = Pdf.open(file)
                version = max(version, src_pdf.pdf_version)
                merged_pdf.pages.extend(src_pdf.pages)

        merged_pdf_file = tempfile.NamedTemporaryFile(mode="w+b", delete=False)
        merged_pdf.save(merged_pdf_file, compress_streams=False)

        # Use PyPDF2 to clean the pdf from any links and Javascript.
        writer = PdfFileWriter()
        reader = PdfFileReader(merged_pdf_file, strict=False)
        [writer.addPage(reader.getPage(i)) for i in range(0, reader.getNumPages())]
        writer.removeLinks()
        with tempfile.NamedTemporaryFile(
            mode="w+b", delete=False
        ) as merged_and_cleaned_pdf_file:
            writer.write(merged_and_cleaned_pdf_file)
            merged_and_cleaned_pdf_file.seek(0)
            merged_and_cleaned_pdf_content = merged_and_cleaned_pdf_file.read()

        pdf = Attachment(
            mimetype="application/pdf",
            bucket=None,
            file_name=attachment_name,
            full_path=None,
            content=merged_and_cleaned_pdf_content,
        )

        self._email.attachments = [pdf] + self._email.attachments

    def _read_gcs(self, bucket_name: str, file_name: str):
        """
        Reads a file from google cloud storage.
        """

        bucket = self._gcs_client.get_bucket(bucket_name)
        blob = bucket.get_blob(file_name)
        content = blob.download_as_bytes()

        return content

    def _send_email(
        self,
        account,
        subject,
        body,
        recipients,
        attachments: [Attachment] = None,
        reply_to: [str] = [],
    ):
        """
        Send an email.

        Parameters
        ----------
        account : Account object
        subject : str
        body : str
        recipients : list of str
            Each str is and email adress
        attachments : list of tuples or None
            (filename, binary contents)

        Examples
        --------
        >>> send_email(account, 'Subject line', 'Hello!', ['info@example.com'])
        """
        to_recipients = []
        for recipient in recipients:
            to_recipients.append(Mailbox(email_address=recipient))

        reply_to_addresses = []
        for address in reply_to:
            reply_to_addresses.append(Mailbox(email_address=address))

        m = Message(
            account=account,
            folder=account.sent,
            subject=subject,
            body=HTMLBody(body),
            to_recipients=to_recipients,
            reply_to=reply_to,
        )

        # attach files
        for attachment in attachments or []:
            file = FileAttachment(name=attachment.file_name, content=attachment.content)
            m.attach(file)
        logging.info("Sending mail to {}".format(to_recipients))
        m.send_and_save()

    def _send_reply_email(self, template: str):
        with open(template) as file_:
            template = Template(file_.read())
        body = template.render(email=self._email)
        subject = "Re: {}".format(self._email.subject)[:255]

        if self._email.sender.lower() == self._email.recipient.lower():
            logging.info(
                "Skipped sending email {} to mailbox {}, identical sender and recipient.".format(
                    subject, self._email.sender
                )
            )
            return
        if self._email.sender.lower() in self._config.ignore_reply_senders:
            logging.info(
                "Skipped sending email {} from sender {}. Sender is on ignore list".format(
                    subject, self._email.sender
                )
            )
            return
        if (
            len(
                [
                    x
                    for x in self._config.ignore_reply_subjects
                    if self._email.subject.startswith(x)
                ]
            )
            > 0
        ):
            logging.info(
                "Skipped sending email {} from sender {}. Subject is on ignore list.".format(
                    subject, self._email.sender
                )
            )
            return

        logging.info(
            "Sending email {} to {} from mailbox {}".format(
                subject, self._email.sender, self._email.recipient
            )
        )

        self._send_email(
            account=self._reply_email_account,
            subject=subject,
            body=body,
            recipients=[self._email.sender],
            attachments=[],
            reply_to=[self._config.reply_to_email],
        )
