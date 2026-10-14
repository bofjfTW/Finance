"""
Kill Switch Controller
Provides programmatic and manual veto over trading system.
"""
import logging

logger = logging.getLogger("KillSwitch")


class KillSwitch:
    def __init__(self):
        self._is_active = False
        self._trigger_reason = ""

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def reason(self) -> str:
        return self._trigger_reason

    def trigger(self, reason: str):
        self._is_active = True
        self._trigger_reason = reason
        logger.critical(f"[ALERT] KILL SWITCH ACTIVATED! Reason: {reason}. All new orders blocked.")

    def reset(self, authorized_by: str = "ADMIN"):
        logger.warning(f"Kill switch manually reset by {authorized_by}.")
        self._is_active = False
        self._trigger_reason = ""
