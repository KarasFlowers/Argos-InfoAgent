from pydantic import BaseModel, Field, field_validator


class BoardTemplateProfileMixin(BaseModel):
    template_profile: dict | None = None

    @field_validator("template_profile")
    @classmethod
    def _template_profile_must_be_object(cls, value):
        if value is not None and not isinstance(value, dict):
            raise ValueError("template_profile must be an object.")
        return value


class BoardCreateRequest(BoardTemplateProfileMixin):
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_\-]+$")
    name: str = Field(min_length=1, max_length=128)
    icon: str = Field(default="", max_length=32)
    description: str = Field(default="", max_length=500)
    system_prompt: str = Field(default="", max_length=4000)
    source_type: str = Field(default="rss", max_length=32)
    source_config: dict = Field(default_factory=dict)
    display_order: int = Field(default=0)
    schedule: str = Field(default="")
    notify_channels: str = Field(default="")
    perspectives: dict | None = None
    prompt_key: str = Field(default="daily_briefing")
    output_language: str = Field(default="auto", pattern=r"^(auto|zh|en)$")
    catchup_days: int = Field(default=7, ge=0, le=30)


class BoardUpdateRequest(BoardTemplateProfileMixin):
    name: str | None = Field(default=None, max_length=128)
    icon: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=500)
    system_prompt: str | None = Field(default=None, max_length=4000)
    source_type: str | None = Field(default=None, max_length=32)
    source_config: dict | None = None
    display_order: int | None = None
    is_active: bool | None = None
    schedule: str | None = None
    notify_channels: str | None = None
    perspectives: dict | None = None
    prompt_key: str | None = None
    output_language: str | None = Field(default=None, pattern=r"^(auto|zh|en)$")
    catchup_days: int | None = Field(default=None, ge=0, le=30)


class BoardPreviewRequest(BoardTemplateProfileMixin):
    slug: str = Field(default="preview-board", min_length=1, max_length=64, pattern=r"^[a-z0-9_\-]+$")
    name: str = Field(default="预览板块", min_length=1, max_length=128)
    icon: str = Field(default="📌", max_length=32)
    description: str = Field(default="", max_length=500)
    system_prompt: str = Field(default="", max_length=4000)
    source_type: str = Field(default="rss", max_length=32)
    source_config: dict = Field(default_factory=dict)
    schedule: str = Field(default="")
    notify_channels: str = Field(default="")
    perspectives: dict | None = None
    prompt_key: str = Field(default="daily_briefing")
    original_slug: str | None = Field(default=None, max_length=64, pattern=r"^[a-z0-9_\-]+$")
    perspective: str = Field(default="overview", max_length=64)
    output_language: str = Field(default="auto", pattern=r"^(auto|zh|en)$")


class BoardWizardMessage(BaseModel):
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class BoardWizardRequest(BaseModel):
    messages: list[BoardWizardMessage] = Field(min_length=1, max_length=20)
    # Optional context for natural-language modification: the most recent
    # suggested config and its validation results, so the LLM can refine rather
    # than start over.
    current_config: dict | None = None
    source_validation: list[dict] | None = None


class BoardSourceCreateRequest(BaseModel):
    url: str = Field(min_length=5, max_length=2048)
    name: str = Field(default="", max_length=200)
    credibility_override: str = Field(
        default="",
        pattern=r"^(|official|established|specialist|community|aggregator|mirror|ai_generated|risky)$",
    )


class BoardSourceUpdateRequest(BaseModel):
    url: str | None = Field(default=None, min_length=5, max_length=2048)
    name: str | None = Field(default=None, max_length=200)
    enabled: bool | None = None
    credibility_override: str | None = Field(
        default=None,
        pattern=r"^(|official|established|specialist|community|aggregator|mirror|ai_generated|risky)$",
    )


class BoardSourceDiscoverRequest(BaseModel):
    query: str = Field(default="", max_length=500)
    limit: int = Field(default=6, ge=1, le=12)
