import json
import base64
import config
import logging

from dacite import from_dict


from mail import Email, GmailConfig, MailProcessor


def handler(request):
    """
    Handler function that extracts a mail message
    from a pubsub message for processing.
    """

    try:
        envelope = json.loads(request.data.decode('utf-8'))
        bytes = base64.b64decode(envelope['message'])
        message = json.loads(bytes)
    except Exception:
        logging.exception('Failed while extracting message!')

    email = from_dict(data_class=Email, data=message['email'])

    configuration = GmailConfig(
        service_account_email=config.GMAIL_SERVICE_ACCOUNT,
        subject_address=config.GMAIL_SUBJECT_ADDRESS,
        scopes=config.GMAIL_SCOPES,
        mail_to=config.GMAIL_SEND_TO_ADDRESS,
        mail_from=config.GMAIL_SEND_AS_ADDRESS,
        mail_reply_to=config.GMAIL_REPLY_TO_ADDRESS,
        merge_pdfs=config.GMAIL_MERGE_PDF,
        pdf_only=config.GMAIL_PDF_ONLY)

    processor = MailProcessor(email, configuration)

    processor.send()


handler(None)
