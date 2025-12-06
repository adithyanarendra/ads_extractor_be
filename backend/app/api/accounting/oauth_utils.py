import os
import requests
from typing import Dict


class ZohoOAuth:
    """
    Handles Zoho OAuth for all regions (US/IN/EU/AU)
    """

    def __init__(self):
        self.client_id = os.getenv("ZOHO_CLIENT_ID")
        self.client_secret = os.getenv("ZOHO_CLIENT_SECRET")
        self.redirect_uri = os.getenv("ZOHO_REDIRECT_URI")


        self.default_dc_domain = "https://accounts.zoho.com"

    # ------------------------------------------------------------
    # STEP 1 — Generate Auth URL
    # ------------------------------------------------------------
    def get_auth_url(self, state: str = "random_state_string"):
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "ZohoBooks.fullaccess.all",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }

        query = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"{self.default_dc_domain}/oauth/v2/auth?{query}"

    # ------------------------------------------------------------
    # STEP 2 — Exchange Authorization Code for Tokens
    # ------------------------------------------------------------
    async def exchange_code_for_token(self, code: str, dc_domain: str) -> Dict:
        """
        Exchange authorization code for access + refresh token.
        Uses dc_domain from Zoho callback (important!)
        """
        token_url = f"{dc_domain}/oauth/v2/token"

        data = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "code": code,
        }

        try:
            response = requests.post(token_url, data=data)
            result = response.json()

            # Debug log
            print("EXCHANGE RESPONSE:", result)

            return result

        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------
    # STEP 3 — Refresh Access Token
    # ------------------------------------------------------------
    def refresh_access_token(self, refresh_token: str, dc_domain: str) -> Dict:
        """
        Refresh Zoho access token using region-specific dc_domain.
        """
        token_url = f"{dc_domain}/oauth/v2/token"

        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token
        }

        try:
            response = requests.post(token_url, data=data)
            result = response.json()

            print("REFRESH RESPONSE:", result)
            return result

        except Exception as e:
            return {"error": str(e)}
