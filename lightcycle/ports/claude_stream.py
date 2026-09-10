from abc import ABC, abstractmethod


class ClaudeStreamPort(ABC):
    @abstractmethod
    def parse_usage_event(self, lines):
        pass

    @abstractmethod
    def parse_attribution_event(self, lines):
        pass

    @abstractmethod
    def parse_attribution_chunk(self, lines, seen_message_ids, pending_tool_use):
        pass

    @abstractmethod
    def parse_rate_limit_event(self, lines):
        pass

    @abstractmethod
    def extract_claimed_step(self, lines, limit=60):
        pass

    @abstractmethod
    def saw_terminal_command(self, lines):
        pass

    @abstractmethod
    def saw_session_activity(self, lines):
        pass
