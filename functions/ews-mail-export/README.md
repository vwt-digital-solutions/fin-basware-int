# EWS Mail Export
This function consumes messages containing e-mails posted on a Pub/Sub Topic and emails them.

## Setup
1. Make sure a ```config.py``` file exists within the directory, based on the [config.example.py](config.example.py), with the correct configuration:
    ~~~
    EMAILS_SENDER_RECEIVER_MAPPING = Dictionary mapping about where the email should be send to and where it should come from
    HARDCODED_RECIPIENTS = Boolean whether the function can only send mails to certain recipients
    NEEDS_PDFS = Boolean whether the send email needs PDFs or not
    MERGE_PDF = Boolean whether the PDFs send along with the email should be merged or not
    PDF_ONLY = Boolean whether there are only PDFs or not
    SEND_REPLIES = Boolean whether a reply should be send or not
    EXCHANGE_URL = The Exchange Web Server URL
    EXCHANGE_VERSION = The Exchange Web Server version
    REPLY_TO_EMAIL_ADDRESS = The email address to reply to
    IGNORE_REPLY_SUBJECTS = A list of subjects in emails that need no reply
    IGNORE_REPLY_SENDERS = A list of email senders that need no reply
    EMAIL_ADDRESS = The email address from which to send emails
    SECRET_ID = The secret ID of the password of this email address
    ~~~
2. Make sure there is a [templates](templates-examples) folder if you set ```SEND_REPLIES``` to True.
3. Make sure the following variables are present in the environment:
    ~~~
    PROJECT_ID = The Google Cloud Platform project ID
    ~~~
4. Deploy the function with help of the [cloudbuild.example.yaml](cloudbuild.example.yaml) to the Google Cloud Platform.

### Sender Reciever Mapping
The field ```EMAILS_SENDER_RECEIVER_MAPPING``` should look as follows:  
If the boolean ```HARDCODED_RECIPIENTS``` is True:  
~~~JSON
{
    "recipient_email_address": {
        "recipient_email": "recipient-email-address",
        "sender_account": "sender-email-account",
        "sender_account_secret": "sender-email-account-secret"
    }
}
~~~
If the boolean ```HARDCODED_RECIPIENTS``` is False:  
~~~JSON
{
    "STANDARD": {
        "sender_account": "sender-email-account",
        "sender_account_secret": "sender-email-account-secret"
    }
}
~~~

## Incoming message
To make sure the function works according to the way it was intented, the incoming messages from a Pub/Sub Topic must have the following structure based on the [company-data structure](https://vwt-digital.github.io/project-company-data.github.io/v1.1/schema):
~~~JSON
{
    "gobits": [],
    "email": {
        "sent_on": "",
        "received_on": "",
        "sender": "",
        "recipient": "",
        "subject": "",
        "body": "",
        "attachments": []
    }
}
~~~

Where attachments is a list containing of objects that look as follows:
~~~JSON
{
    "mimetype": "",
    "bucket": "",
    "file_name": "",
    "full_path": ""
}
~~~

## License
This function is licensed under the [GPL-3](https://www.gnu.org/licenses/gpl-3.0.en.html) License
