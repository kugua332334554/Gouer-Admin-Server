# Pydantic request/response models for all API endpoints
from pydantic import BaseModel
from typing import Optional

# ── Auth ──────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: str = ""
    captcha_id: str = ""
    captcha_answer: str = ""

class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str

class UsernameChangeRequest(BaseModel):
    password: str
    totp_code: str
    new_username: str

class TwoFAResetRequest(BaseModel):
    password: str
    totp_code: str

# ── Groups ────────────────────────────────────────────
class GroupInfoUpdate(BaseModel):
    title: Optional[str] = None
    username: Optional[str] = None
    type: Optional[str] = None

class GroupVerifyUpdate(BaseModel):
    verify_status: Optional[bool] = None
    verify_mode: Optional[str] = None
    verify_duration: Optional[int] = None
    verify_penalty: Optional[str] = None
    block_blacklist: Optional[bool] = None

class BlacklistCreate(BaseModel):
    user_id: int
    username: str = ""
    reason: str = ""

class WelcomeSettingsUpdate(BaseModel):
    status: Optional[bool] = None
    delete_time: Optional[int] = None
    delete_last: Optional[bool] = None
    welcome_text: Optional[str] = None
    buttons_text: Optional[str] = None

class NightSettingsUpdate(BaseModel):
    status: Optional[bool] = None
    start_hour: Optional[int] = None
    end_hour: Optional[int] = None
    notify: Optional[bool] = None

class AntispamUpdate(BaseModel):
    enabled: Optional[bool] = None
    block_contact: Optional[bool] = None
    block_location: Optional[bool] = None
    block_channel_send: Optional[bool] = None
    block_channel_fwd: Optional[bool] = None
    block_external_ref: Optional[bool] = None
    block_exe: Optional[bool] = None
    block_mention: Optional[bool] = None
    block_links: Optional[bool] = None
    block_long_links: Optional[bool] = None
    block_visitor_bots: Optional[bool] = None
    block_flood: Optional[bool] = None
    flood_timeout: Optional[int] = None
    flood_count: Optional[int] = None
    penalty: Optional[str] = None
    mute_duration: Optional[int] = None
    whitelist: Optional[str] = None
    warn_delete: Optional[int] = None

class ChatAISettings(BaseModel):
    chat_enabled: Optional[bool] = None
    chat_prompt: Optional[str] = None
    chat_trigger: Optional[str] = None
    audit_enabled: Optional[bool] = None
    audit_penalty: Optional[str] = None

class ToggleSettings(BaseModel):
    enabled: Optional[bool] = None
    open_keyword: Optional[str] = None
    open_text: Optional[str] = None
    close_keyword: Optional[str] = None
    close_text: Optional[str] = None

class PointsSettings(BaseModel):
    status: Optional[bool] = None
    msg_points: Optional[int] = None
    ignore_stickers: Optional[bool] = None
    delete_time: Optional[int] = None

class SpeakCheckSettings(BaseModel):
    enabled: Optional[bool] = None
    require_last_name: Optional[bool] = None
    require_username: Optional[bool] = None
    require_photo: Optional[bool] = None
    require_premium: Optional[bool] = None
    require_channel: Optional[bool] = None
    channel_username: Optional[str] = None
    penalty: Optional[str] = None
    mute_duration: Optional[int] = None
    warn_delete: Optional[int] = None

class AutodeleteUpdate(BaseModel):
    pin: Optional[bool] = None
    photo: Optional[bool] = None
    title: Optional[bool] = None
    join_leave: Optional[bool] = None

class CardSettingsUpdate(BaseModel):
    enabled: Optional[bool] = None
    template: Optional[str] = None

class PermissionUpdate(BaseModel):
    permissions: str = "all"

# ── Features ──────────────────────────────────────────
class DingshiCreate(BaseModel):
    chat_id: int
    schedule_time: str
    schedule_days: str = "*"
    interval_minutes: int = 0
    content_text: str = ""
    buttons_text: str = ""
    status: bool = True

class KeywordCreate(BaseModel):
    chat_id: int
    word: str
    penalty: str = "delete"
    mute_duration: int = 3600
    status: bool = True

class FortuneCreate(BaseModel):
    sign: str
    poem: str
    reading: str = ""

class KeywordReplyCreate(BaseModel):
    chat_id: int
    keyword: str
    match_mode: str = "contains"
    reply_text: str = ""
    buttons_text: str = ""
    status: bool = True

class QuickPublishCreate(BaseModel):
    creator_id: int = 0
    name: str
    keyword: str
    content_text: str = ""
    buttons_text: str = ""
    status: bool = True

class PointsUpdateModel(BaseModel):
    points: int

# ── Subscriptions ─────────────────────────────────────
class SubscriptionUpdate(BaseModel):
    chat_id: int
    feature: str
    days: int = 30

class SubscriptionEditRequest(BaseModel):
    chat_id: Optional[int] = None
    feature: Optional[str] = None
    days: Optional[int] = None
    expires_at: Optional[str] = None

# ── Bot Tokens ────────────────────────────────────────
class BotTokenCreate(BaseModel):
    owner_id: int
    bot_token: str
    bot_username: str = ""

# ── Users ─────────────────────────────────────────────
class UserUpdate(BaseModel):
    username: Optional[str] = None
    first_name: Optional[str] = None
    bio: Optional[str] = None
    timezone: Optional[str] = None
    language: Optional[str] = None

# ── DB Manager ────────────────────────────────────────
class DBQueryRequest(BaseModel):
    sql: str
    limit: int = 100

# ── Code Editor ───────────────────────────────────────
class FileSaveRequest(BaseModel):
    path: str
    content: str
    scope: str = "plugins"
