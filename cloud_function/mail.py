import io
import base64
import logging
import google.auth
import googleapiclient.discovery

from typing import List, Optional
from dataclasses import dataclass

from google.cloud import storage
from google.auth import iam
from google.auth.transport import requests
from google.oauth2 import service_account

from email import encoders
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from PyPDF2 import PdfFileMerger, PdfFileReader


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
    subject: str
    body: str
    attachments: List[Attachment]


@dataclass
class GmailConfig:
    service_account_email: str
    subject_address: str
    scopes: str
    mail_to: str
    mail_from: str
    mail_reply_to: str
    pdf_only: bool
    merge_pdfs: bool


class MailProcessor:

    def __init__(self, email: Email, config: GmailConfig):
        self._email = email
        self._config = config
        self._gcs_client = storage.Client()

    def send(self):
        """
        Sends an e-mail as "me" using the mail service and message body.
        """

        body = self._generate_body()

        message = (self._mail_service().users().messages().send(
            userId="me",
            body=body).execute())

        logging.info(f"Sent message with id {message['id']}")

    def _generate_body(self):
        """
        Generates an e-mail body.
        """

        message = MIMEMultipart()
        message['to'] = self._config.mail_to
        message['from'] = self._config.mail_from
        message['subject'] = self._email.subject
        message['reply-to'] = self._config.mail_reply_to

        text = MIMEText(self._email.body, 'plain')
        message.attach(text)

        attachments = self._get_attachments()

        for attachment in attachments:
            message.attach(attachment)

        raw = base64.urlsafe_b64encode(
            message.as_bytes()).decode()

        return {'raw': raw}

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

        attachments = []

        for attachment in self._email.attachments:
            main_type, sub_type = attachment.mimetype.split('/', 1)
            file = MIMEBase(main_type, sub_type)
            file.set_payload(attachment.content)
            file.add_header('Content-Disposition',
                            'attachment',
                            filename=attachment.file_name)
            encoders.encode_base64(file)
            attachments.append(file)

        return attachments

    def _merge_pdfs(self, attachment_name: str):
        """
        Merges pdf attachments to a single file.
        """

        attachments = self._email.attachments

        self._email.attachments = [a for a in attachments if not a.mimetype.endswith("pdf")]

        merger = PdfFileMerger()
        for attachment in attachments:
            with io.BytesIO(attachment.content) as file:
                merger.append(PdfFileReader(file))

        logging.info(f"Merged {len(attachments)} pdf attachments")

        content = io.BytesIO()
        merger.write(content)
        merger.close()

        pdf = Attachment(
            mimetype='application/pdf',
            bucket=None,
            file_name=attachment_name,
            full_path=None,
            content=content.getvalue()
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

    def _mail_service(self):
        """
        Creates a gmail service.
        """

        credentials, project_id = google.auth.default(
            scopes=['https://www.googleapis.com/auth/iam'])

        delegated_credentials = self._delegated_credentials(credentials)

        service = googleapiclient.discovery.build(
            'gmail', 'v1',
            credentials=delegated_credentials,
            cache_discovery=False)

        return service

    def _delegated_credentials(self, credentials):
        """
        Creates delegated credentials.
        """

        request = requests.Request()
        credentials.refresh(request)

        signer = iam.Signer(
            request,
            credentials,
            self._config.service_account_email)

        credentials = service_account.Credentials(
            signer=signer,
            service_account_email=self._config.service_account_email,
            token_uri='https://accounts.google.com/o/oauth2/token',
            scopes=self._config.scopes,
            subject=self._config.subject_address)

        return credentials
