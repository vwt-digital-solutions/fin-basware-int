import io
import logging
import tempfile

from typing import List, Optional
from dataclasses import dataclass

from PyPDF2 import PdfFileWriter, PdfFileReader
from exchangelib import FileAttachment, Message, Mailbox, Account, Credentials, Configuration, FaultTolerance
from google.cloud import storage

from pikepdf import Pdf


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
    pdf_only: bool
    merge_pdfs: bool


class MailProcessor:

    def __init__(self, email: Email, config: EWSConfig):
        self._email = email
        self._config = config
        self._gcs_client = storage.Client()
        credentials = Credentials(config.email_account, config.password)
        ews_config = Configuration(auth_type='basic', retry_policy=FaultTolerance(max_wait=300))
        self._account = Account(config.email_account, credentials=credentials, autodiscover=True, config=ews_config)

    def _send_email(self, account, subject, body, recipients, attachments: [Attachment] = None):
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
        # Create message
        m = Message(account=account,
                    folder=account.sent,
                    subject=subject,
                    body=body,
                    to_recipients=to_recipients)

        # attach files
        for attachment in attachments or []:
            file = FileAttachment(name=attachment.file_name, content=attachment.content)
            m.attach(file)
        logging.info('Sending mail to {}'.format(to_recipients))
        m.send_and_save()

    def send(self):
        """
        Sends an e-mail as "me" using the mail service and message body.
        """
        self._get_attachments()
        recipient = self._config.mail_to_mapping.get(self._email.recipient)
        self._send_email(self._account, self._email.subject, self._email.body, [recipient], self._email.attachments)

    def _get_attachments(self):
        """
        Downloads attachments from a gcs bucket.
        Filters and merges pdf attachments if applicable.
        """

        if self._config.pdf_only:
            for idx, attachment in enumerate(self._email.attachments):
                if not attachment.mimetype.endswith("pdf"):
                    self._email.attachments.pop(idx)

        for attachment in self._email.attachments:
            attachment.content = self._read_gcs(
                attachment.bucket,
                attachment.full_path)

            logging.info(f"Downloaded attachment {attachment.file_name}")

        if self._email.attachments and self._config.merge_pdfs:
            first_attachment = next(iter(self._email.attachments))
            attachment_name = first_attachment.file_name
            self._merge_pdfs(attachment_name)

    def _merge_pdfs(self, attachment_name: str):
        """
        Merges pdf attachments to a single file.
        This function uses both pikePDF (For merging), and pyPDF2 (for cleaning).
        An initial implementation used only pyPDF2, but that proved to problematic since pyPDF
        has quite a lot of trouble merging different types of PDFs. Since pikePDF doesn't feature sanitizing pdfs,
        we run it through pikepdf afterwards.
        """

        attachments = self._email.attachments
        self._email.attachments = [a for a in attachments if not a.mimetype.endswith("pdf")]

        # Go through all attachments and merge them using pikePDF
        merged_pdf = Pdf.new()
        version = merged_pdf.pdf_version

        for attachment in attachments:
            with io.BytesIO(attachment.content) as file:
                src_pdf = Pdf.open(file)
                version = max(version, src_pdf.pdf_version)
                merged_pdf.pages.extend(src_pdf.pages)

        merged_pdf.remove_unreferenced_resources()

        merged_pdf_file = tempfile.NamedTemporaryFile(mode='w+b', delete=False)
        merged_pdf.save(merged_pdf_file)

        # Use PyPDF2 to clean the pdf from any links and Javascript.
        writer = PdfFileWriter()
        reader = PdfFileReader(merged_pdf_file, strict=False)
        [writer.addPage(reader.getPage(i)) for i in range(0, reader.getNumPages())]
        writer.removeLinks()
        with tempfile.NamedTemporaryFile(mode='w+b', delete=False) as merged_and_cleaned_pdf_file:
            writer.write(merged_and_cleaned_pdf_file)
            merged_and_cleaned_pdf_file.seek(0)
            merged_and_cleaned_pdf_content = merged_and_cleaned_pdf_file.read()

        pdf = Attachment(
            mimetype='application/pdf',
            bucket=None,
            file_name=attachment_name,
            full_path=None,
            content=merged_and_cleaned_pdf_content
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
