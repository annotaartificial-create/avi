import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings

from payment.models import PaymentLedger, Wallet
from payment.providers import get_payment_provider, PaymentProviderError
from payment.providers.base import TransactionStatusResult
from payment.providers.lipalink import LipaLinkProvider


class LipaLinkProviderTests(TestCase):
    def setUp(self):
        self.api_key = "test_lipalink_api_key_123"
        self.business_id = 12

    @override_settings(LIPALINK_API_KEY="test_lipalink_api_key_123", LIPALINK_BUSINESS_ID="12")
    def test_factory_resolves_lipalink(self):
        provider = get_payment_provider("lipalink")
        self.assertIsInstance(provider, LipaLinkProvider)
        self.assertEqual(provider.name, "lipalink")

    @override_settings(LIPALINK_API_KEY="test_lipalink_api_key_123", LIPALINK_BUSINESS_ID="12")
    @patch("payment.providers.lipalink.requests.post")
    def test_initiate_deposit_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": True,
            "transaction_id": "PFX20260101ABCDEF",
            "status": "Pending",
            "message": "STK push sent. Ask the customer to enter their M-Pesa PIN."
        }
        mock_post.return_value = mock_resp

        provider = LipaLinkProvider()
        result = provider.initiate_deposit(
            reference="DEP-20261029125500-1",
            phone="0712345678",
            amount_kes=100,
            amount_usd=Decimal("0.00"),
        )

        self.assertTrue(result.success)
        self.assertEqual(result.provider_reference, "PFX20260101ABCDEF")
        self.assertEqual(result.resource_location, "PFX20260101ABCDEF")
        self.assertIn("STK push sent", result.message)

        # Verify call arguments
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://lipalink.co.ke/api/stk_push.php")
        self.assertEqual(kwargs["headers"]["X-Api-Key"], self.api_key)
        self.assertEqual(kwargs["json"]["msisdn"], "254712345678")
        self.assertEqual(kwargs["json"]["amount"], 100)
        self.assertEqual(kwargs["json"]["business_id"], 12)
        self.assertEqual(kwargs["json"]["reference"], "DEP-20261029125500-1")

    @override_settings(LIPALINK_API_KEY="test_lipalink_api_key_123", LIPALINK_BUSINESS_ID="12")
    @patch("payment.providers.lipalink.requests.get")
    def test_query_deposit_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": True,
            "transaction_id": "PFX20260101ABCDEF",
            "status": "Success",
            "amount": 100,
            "msisdn": "254712345678",
            "mpesa_receipt": "TJ7ABC12XY",
            "reference": "ORDER-001",
            "result_desc": "The service request is processed successfully.",
            "transaction_date": "2026-10-07 10:14:00",
            "currency": "KES",
            "country": "KEN"
        }
        mock_get.return_value = mock_resp

        provider = LipaLinkProvider()
        result = provider.query_deposit(provider_reference="PFX20260101ABCDEF")

        self.assertEqual(result.status, "paid")
        self.assertEqual(result.provider_reference, "PFX20260101ABCDEF")
        self.assertEqual(result.receipt_number, "TJ7ABC12XY")

    @override_settings(LIPALINK_API_KEY="test_lipalink_api_key_123", LIPALINK_BUSINESS_ID="12")
    @patch("payment.providers.lipalink.requests.get")
    def test_query_deposit_failed(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": True,
            "transaction_id": "PFX20260101ABCDEF",
            "status": "Failed",
            "result_desc": "Request Cancelled by user."
        }
        mock_get.return_value = mock_resp

        provider = LipaLinkProvider()
        result = provider.query_deposit(provider_reference="PFX20260101ABCDEF")

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.reason, "Request Cancelled by user.")

    @override_settings(LIPALINK_API_KEY="test_lipalink_api_key_123", LIPALINK_BUSINESS_ID="12")
    def test_parse_webhook_with_valid_hmac(self):
        payload = {
            "event": "payment.success",
            "transaction_id": "PFX20260101ABCDEF",
            "status": "Success",
            "amount": 1500,
            "currency": "KES",
            "amount_kes": 1500,
            "fx_rate": 1,
            "msisdn": "256771234567",
            "mpesa_receipt": "TJ7ABC12XY",
            "reference": "ORDER-001",
            "business_id": 12,
            "country": "UGA",
            "provider": "MPESA_XB",
            "redirected": False,
            "transaction_date": "2026-10-07 10:14:00",
            "test": False
        }
        raw_body = json.dumps(payload).encode("utf-8")
        timestamp = "1760000000"
        signature_mac = hmac.new(
            self.api_key.encode("utf-8"),
            f"{timestamp}.{raw_body.decode('utf-8')}".encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        headers = {
            "X-Pesaflux-Event": "payment.success",
            "X-Pesaflux-Signature": f"t={timestamp},v1={signature_mac}"
        }

        provider = LipaLinkProvider()
        parsed = provider.parse_webhook(raw_body=raw_body, headers=headers)

        self.assertEqual(parsed.status, "paid")
        self.assertEqual(parsed.reference, "ORDER-001")
        self.assertEqual(parsed.provider_reference, "PFX20260101ABCDEF")
        self.assertEqual(parsed.receipt_number, "TJ7ABC12XY")

    @override_settings(LIPALINK_API_KEY="test_lipalink_api_key_123", LIPALINK_BUSINESS_ID="12")
    def test_parse_webhook_invalid_hmac_raises_error(self):
        raw_body = b'{"status": "Success", "reference": "ORDER-001"}'
        headers = {
            "X-Pesaflux-Signature": "t=1760000000,v1=tampered_signature_hex"
        }

        provider = LipaLinkProvider()
        with self.assertRaises(PaymentProviderError) as ctx:
            provider.parse_webhook(raw_body=raw_body, headers=headers)

        self.assertIn("signature", str(ctx.exception).lower())


class DepositStatusPollingTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.user = User.objects.create_user(
            email="testplayer@example.com",
            password="testpassword123",
            username="testplayer",
        )
        self.wallet, _ = Wallet.objects.get_or_create(user=self.user)
        self.wallet.balance = Decimal("50.00")
        self.wallet.save(update_fields=["balance"])
        self.client.force_login(self.user)

    def test_deposit_status_view_returns_completed_immediately_if_already_completed(self):
        ledger = PaymentLedger.objects.create(
            user=self.user,
            wallet=self.wallet,
            transaction_type=PaymentLedger.TransactionType.DEPOSIT,
            provider="lipalink",
            reference="DEP-TEST-001",
            phone="254712345678",
            amount=Decimal("100.00"),
            status=PaymentLedger.Status.COMPLETED,
            receipt_number="TESTREC123",
        )

        with patch("payment.providers.factory.get_payment_provider") as mock_get_provider:
            response = self.client.get(f"/payment/deposit/status/{ledger.reference}/")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "COMPLETED")
            self.assertEqual(data["receipt"], "TESTREC123")
            # Should NOT have queried the external provider because local check was completed
            mock_get_provider.assert_not_called()

    def test_deposit_status_view_polls_provider_and_updates_on_paid(self):
        ledger = PaymentLedger.objects.create(
            user=self.user,
            wallet=self.wallet,
            transaction_type=PaymentLedger.TransactionType.DEPOSIT,
            provider="lipalink",
            reference="DEP-TEST-002",
            provider_reference="PFX123456",
            phone="254712345678",
            amount=Decimal("200.00"),
            status=PaymentLedger.Status.PENDING,
        )

        mock_provider = MagicMock()
        mock_provider.name = "lipalink"
        mock_provider.query_deposit.return_value = TransactionStatusResult(
            status="paid",
            provider_reference="PFX123456",
            receipt_number="REC999",
            reason="Confirmed via provider query",
            raw_response={"status": "Success"},
        )

        with patch("payment.views.get_payment_provider", return_value=mock_provider):
            response = self.client.get(f"/payment/deposit/status/{ledger.reference}/")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "COMPLETED")
            self.assertEqual(data["receipt"], "REC999")

            # Check that local database was updated and wallet was credited
            ledger.refresh_from_db()
            self.assertEqual(ledger.status, PaymentLedger.Status.COMPLETED)
            self.assertEqual(ledger.receipt_number, "REC999")
            self.wallet.refresh_from_db()
            self.assertEqual(self.wallet.balance, Decimal("250.00"))

    def test_deposit_status_view_polls_provider_and_updates_on_rejected(self):
        ledger = PaymentLedger.objects.create(
            user=self.user,
            wallet=self.wallet,
            transaction_type=PaymentLedger.TransactionType.DEPOSIT,
            provider="lipalink",
            reference="DEP-TEST-003",
            provider_reference="PFX789",
            phone="254712345678",
            amount=Decimal("150.00"),
            status=PaymentLedger.Status.PENDING,
        )

        mock_provider = MagicMock()
        mock_provider.name = "lipalink"
        mock_provider.query_deposit.return_value = TransactionStatusResult(
            status="rejected",
            provider_reference="PFX789",
            reason="User cancelled the prompt.",
            raw_response={"status": "Failed"},
        )

        with patch("payment.views.get_payment_provider", return_value=mock_provider):
            response = self.client.get(f"/payment/deposit/status/{ledger.reference}/")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "FAILED")
            self.assertIn("cancelled", data["message"].lower())

            ledger.refresh_from_db()
            self.assertEqual(ledger.status, PaymentLedger.Status.FAILED)
            self.wallet.refresh_from_db()
            self.assertEqual(self.wallet.balance, Decimal("50.00"))

    def test_deposit_status_view_polls_provider_returns_pending_if_still_processing(self):
        ledger = PaymentLedger.objects.create(
            user=self.user,
            wallet=self.wallet,
            transaction_type=PaymentLedger.TransactionType.DEPOSIT,
            provider="lipalink",
            reference="DEP-TEST-004",
            provider_reference="PFX999",
            phone="254712345678",
            amount=Decimal("100.00"),
            status=PaymentLedger.Status.PENDING,
        )

        mock_provider = MagicMock()
        mock_provider.name = "lipalink"
        mock_provider.query_deposit.return_value = TransactionStatusResult(
            status="pending",
            provider_reference="PFX999",
            reason="Waiting for user PIN",
            raw_response={"status": "Pending"},
        )

        with patch("payment.views.get_payment_provider", return_value=mock_provider):
            response = self.client.get(f"/payment/deposit/status/{ledger.reference}/")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "PENDING")

            ledger.refresh_from_db()
            self.assertEqual(ledger.status, PaymentLedger.Status.PENDING)
            self.wallet.refresh_from_db()
            self.assertEqual(self.wallet.balance, Decimal("50.00"))

