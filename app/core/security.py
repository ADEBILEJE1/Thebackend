import secrets

def generate_invitation_token() -> str:
    return secrets.token_urlsafe(32)