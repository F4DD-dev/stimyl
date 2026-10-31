from dataclasses import dataclass


@dataclass(frozen=True)
class OutboundButton:
    text: str
    payload: str
    url: str = ""


class NullSender:
    async def send_text(
        self,
        *,
        user_id: str,
        chat_id: int | None,
        text: str,
        buttons: list[OutboundButton],
    ) -> None:
        return None

    async def answer_callback(
        self,
        callback_id: str,
        notification: str | None = None,
        text: str | None = None,
        buttons: list[OutboundButton] | None = None,
    ) -> bool:
        return False

    async def aclose(self) -> None:
        return None
