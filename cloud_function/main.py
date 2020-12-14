import json
import base64
import os

import config
import util
import logging

from dacite import from_dict

from mail import Email, EWSConfig, MailProcessor


def handler(request):
    """
    Handler function that extracts a mail message
    from a pubsub message for processing.
    """

    try:
        envelope = json.loads(request.data.decode('utf-8'))
        logging.info(envelope)
        bytes = base64.b64decode(envelope['message']['data'])
        message = json.loads(bytes)
    except Exception as e:
        logging.exception('Failed while extracting message!')
        raise e

    if message['email'].get('subject', None) is None:
        message['email']['subject'] = ''
    if message['email'].get('body', None) is None:
        message['email']['body'] = ''

    email = from_dict(data_class=Email, data=message['email'])

    configuration = EWSConfig(
        email_account=config.EMAIL_ADDRESS,
        password=util.get_secret(os.environ['PROJECT_ID'], config.SECRET_ID),
        mail_from=config.EMAIL_ADDRESS,
        mail_to_mapping=config.EMAILS_SENDER_RECEIVER_MAPPING,
        pdf_only=config.PDF_ONLY,
        merge_pdfs=config.MERGE_PDF,
    )

    processor = MailProcessor(email, configuration)

    processor.process()


if __name__ == '__main__':
    handler(None)
