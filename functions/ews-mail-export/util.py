from google.cloud import secretmanager


def get_secret(project_id, secret_id):
    """
    Returns a Secret Manager secret.
    """

    client = secretmanager.SecretManagerServiceClient()

    secret_name = client.access_secret_version(
        request={"name": f"projects/{project_id}/secrets/{secret_id}/versions/latest"}
    )

    payload = secret_name.payload.data.decode("UTF-8")

    return payload
