"""Phone Cloud API registration status helpers for WhatsApp Hub flows."""


class TestPhoneNeedsRegistration:
    def test_connected_does_not_need_registration(self):
        from src.utils.whatsapp_phone_status import phone_needs_cloud_registration

        assert phone_needs_cloud_registration("CONNECTED") is False
        assert phone_needs_cloud_registration("connected") is False

    def test_all_non_connected_meta_statuses_need_attention(self):
        from src.utils.whatsapp_phone_status import phone_needs_cloud_registration

        # Meta Manager "Offline" maps to API DISCONNECTED — not PENDING.
        for status in (
            "PENDING",
            "DISCONNECTED",
            "UNVERIFIED",
            "DELETED",
            "MIGRATED",
            "BANNED",
            "RESTRICTED",
            "RATE_LIMITED",
            "FLAGGED",
            "UNKNOWN",
            None,
            "",
        ):
            assert phone_needs_cloud_registration(status) is True, status

    def test_registration_is_primary_for_offline_and_pending(self):
        from src.utils.whatsapp_phone_status import phone_registration_is_primary_action

        assert phone_registration_is_primary_action("DISCONNECTED") is True
        assert phone_registration_is_primary_action("PENDING") is True
        assert phone_registration_is_primary_action("CONNECTED") is False
        assert phone_registration_is_primary_action("BANNED") is False


class TestAlreadyDeregisteredError:
    def test_detects_invalid_parameter_when_offline(self):
        from src.utils.whatsapp_phone_status import is_already_deregistered_error

        payload = {
            "error": {
                "message": "(#100) Invalid parameter",
                "code": 100,
                "error_subcode": 33,
            }
        }
        assert is_already_deregistered_error(400, payload) is True

    def test_other_errors_are_not_already_deregistered(self):
        from src.utils.whatsapp_phone_status import is_already_deregistered_error

        payload = {"error": {"message": "Invalid OAuth access token", "code": 190}}
        assert is_already_deregistered_error(401, payload) is False


class TestResolvePhoneStatusFromMetaList:
    def test_matches_connected_phone_number_id(self):
        from src.utils.whatsapp_phone_status import resolve_phone_status_from_meta_list

        phones = [
            {"id": "111", "status": "PENDING"},
            {"id": "222", "status": "DISCONNECTED"},
        ]
        assert resolve_phone_status_from_meta_list(phones, "222") == "DISCONNECTED"

    def test_missing_phone_defaults_to_pending(self):
        from src.utils.whatsapp_phone_status import resolve_phone_status_from_meta_list

        assert resolve_phone_status_from_meta_list([], "999") == "PENDING"
        assert resolve_phone_status_from_meta_list([{"id": "1"}], "999") == "PENDING"
