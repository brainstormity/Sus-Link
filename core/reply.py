from __future__ import annotations

from typing import Optional
import discord
from typing_extensions import Self

__all__ = ("ReplyView",)

CONTAINER_FOOTER = "-# Built by [@brainstormity](https://x.com/brainstormity)"


class ReplyView(discord.ui.LayoutView):
    def __init__(
        self,
        body: str,
        *,
        accent_color: Optional[int] = None,
        accessory: Optional[discord.ui.Item] = None,
        thumbnail_url: Optional[str] = None,
        accent: Optional[int] = None,
        include_footer: bool = True,
        footer_text: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        color = accent_color if accent_color is not None else accent
        self._container = discord.ui.Container(accent_color=color)
        self.add_item(self._container)
        self.add_body(body, accessory=accessory, thumbnail_url=thumbnail_url)
        if include_footer:
            self.add_footer(footer_text or CONTAINER_FOOTER)

    def add_header_image(self, image_url: str) -> Self:
        media_item = discord.MediaGalleryItem(image_url)
        header_banner_image = discord.ui.MediaGallery(media_item)
        self._container.add_item(header_banner_image)
        return self

    def add_body(
        self,
        body: str,
        accessory: Optional[discord.ui.Item] = None,
        thumbnail_url: Optional[str] = None,
    ) -> Self:
        text_display = discord.ui.TextDisplay(body)

        chosen_accessory = accessory
        if chosen_accessory is None and thumbnail_url:
            ThumbnailClass = getattr(discord.ui, "Thumbnail", None)
            if ThumbnailClass is not None:
                try:
                    chosen_accessory = ThumbnailClass(thumbnail_url)
                except Exception:
                    try:
                        chosen_accessory = ThumbnailClass(media=thumbnail_url)
                    except Exception:
                        chosen_accessory = None

            if chosen_accessory is None:
                ImageClass = getattr(discord.ui, "Image", None)
                if ImageClass is not None:
                    try:
                        chosen_accessory = ImageClass(thumbnail_url)
                    except Exception:
                        chosen_accessory = None

        if chosen_accessory is not None:
            self._container.add_item(
                discord.ui.Section(text_display, accessory=chosen_accessory)
            )
        else:
            self._container.add_item(text_display)
        return self

    def add_separator(
        self,
        spacing: discord.SeparatorSpacing = discord.SeparatorSpacing.small,
        visible: bool = True,
    ) -> Self:
        self._container.add_item(discord.ui.Separator(spacing=spacing, visible=visible))
        return self

    def add_footer(self, text: str = CONTAINER_FOOTER) -> Self:
        self._container.add_item(
            discord.ui.Separator(spacing=discord.SeparatorSpacing.small, visible=False)
        )
        self._container.add_item(discord.ui.TextDisplay(text))
        return self

    def credits(self) -> Self:
        return self.add_footer()
