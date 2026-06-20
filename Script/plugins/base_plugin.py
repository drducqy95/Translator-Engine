class BasePlugin:
    @property
    def source_id(self) -> str:
        raise NotImplementedError

    @property
    def source_name(self) -> str:
        raise NotImplementedError

    def search(self, keyword: str) -> list:
        return []

    def get_toc(self, novel_url: str) -> list:
        return []

    def get_chapter(self, chapter_url: str) -> str:
        return ""
