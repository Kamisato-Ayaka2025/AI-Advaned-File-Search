"""Synthetic contract checks; run with PYTHONPATH=src and unittest discovery."""
from dataclasses import asdict, replace
import json
import unittest

from original_words.contracts import Message, stable_message_id


def sample(**changes):
    values = dict(
        message_id=stable_message_id("synthetic:account-a", "chat-1", original_id="1"),
        source_id="synthetic:account-a", chat_id="chat-1", chat_type="group",
        sender_id="synthetic:sender-1", sender_name="合成参与者", timestamp="2026-01-01T00:00:00Z",
        message_type="text", content="合成测试消息", seq=1, timestamp_status="known",
        timestamp_precision="second", timestamp_source="synthetic_fixture",
        source_timezone="Asia/Shanghai",
    )
    return Message(**(values | changes))


class MessageContractTests(unittest.TestCase):
    def test_round_trip(self):
        message = sample()
        self.assertEqual(Message(**json.loads(json.dumps(asdict(message)))), message)

    def test_source_and_chat_namespace(self):
        ids = {stable_message_id(s, c, original_id="1")
               for s in ("a", "b") for c in ("x", "y")}
        self.assertEqual(len(ids), 4)
        self.assertNotEqual(stable_message_id("a:b", "c", original_id="1"),
                            stable_message_id("a", "b:c", original_id="1"))

    def test_original_id_survives_content_change(self):
        self.assertEqual(stable_message_id("a", "b", original_id="1", content="old"),
                         stable_message_id("a", "b", original_id="1", content="new"))

    def test_fallback_id_is_deterministic_and_sequence_sensitive(self):
        first = stable_message_id("a", "b", seq=1, content="same")
        self.assertEqual(first, stable_message_id("a", "b", seq=1, content="same"))
        self.assertNotEqual(first, stable_message_id("a", "b", seq=2, content="same"))
        for seq in (None, -1, True):
            with self.assertRaises(ValueError):
                stable_message_id("a", "b", seq=seq)

    def test_unknown_time_empty_body_is_preserved(self):
        message = sample(timestamp=None, timestamp_status="unknown",
                         timestamp_precision="unknown", content="", message_type="unknown")
        self.assertTrue(message.matches_time_range(None, None))
        self.assertFalse(message.matches_time_range("2025-01-01T00:00:00Z", None))
        with self.assertRaises(ValueError):
            replace(message, timestamp="2026-01-01T00:00:00Z")

    def test_half_open_boundaries(self):
        message = sample()
        self.assertTrue(message.matches_time_range(message.timestamp, "2026-01-02T00:00:00Z"))
        self.assertFalse(message.matches_time_range(None, message.timestamp))
        self.assertFalse(message.matches_time_range(message.timestamp, message.timestamp))
        with self.assertRaises(ValueError):
            message.matches_time_range("2026-01-02T00:00:00Z", message.timestamp)

    def test_day_precision_is_not_an_invented_instant(self):
        message = sample(timestamp="2026-01-01", timestamp_precision="day")
        self.assertTrue(message.matches_time_range(None, None))
        self.assertFalse(message.matches_time_range("2026-01-01T00:00:00Z", None))
        with self.assertRaises(ValueError):
            replace(message, timestamp="2026-01-01T00:00:00Z")

    def test_invalid_enums_and_non_utc_rejected(self):
        for changes in ({"timestamp": "2026-01-01T08:00:00+08:00"},
                        {"timestamp": "2026-01-01T00:00:00"},
                        {"message_type": "guessed"}, {"seq": True},
                        {"timestamp_source": None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                sample(**changes)

    def test_sensitive_payload_not_in_repr_or_validation_error(self):
        secret = "SYNTHETIC_PRIVATE_SENTINEL"
        self.assertNotIn(secret, repr(sample(content=secret, raw_payload=secret)))
        with self.assertRaises(ValueError) as error:
            sample(timestamp=secret)
        self.assertNotIn(secret, str(error.exception))


if __name__ == "__main__":
    unittest.main()
