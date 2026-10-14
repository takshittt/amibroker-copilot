"""Record formats for the knowledge base files in /kb.

Every record rejects unknown fields and missing fields. Values are not
coerced: a number where text is expected is an error, because YAML reads
unquoted `15:30` as 930 and unquoted `True`, `False` and `Null` as
booleans and null.
"""

import datetime
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

DOC_URL_PREFIX = "https://www.amibroker.com/"


def _must_be_text(value: Any) -> Any:
    if not isinstance(value, str):
        raise ValueError(f"expected text but YAML read {value!r}; put quotes around the value")
    return value


Text = Annotated[str, BeforeValidator(_must_be_text), StringConstraints(min_length=1)]
Identifier = Annotated[
    str,
    BeforeValidator(_must_be_text),
    StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$"),
]
# 24-hour "HH:MM", in the exchange's local time.
TimeOfDay = Annotated[
    str,
    BeforeValidator(_must_be_text),
    StringConstraints(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$"),
]

ParamType = Literal["array", "number", "string", "any"]
# "any" means the result depends on the arguments (IIf, Max, abs), so a
# rule that needs to know array or number must treat it as unknown.
ReturnType = Literal["array", "number", "string", "none", "any"]
ValueType = Literal["array", "number", "string"]
Category = Literal[
    "indicator",
    "signal",
    "stops",
    "sizing",
    "time",
    "plot",
    "param",
    "math",
    "lookup",
    "backtest",
    "exploration",
    "statistics",
    "pattern",
    "composite",
    "foreign",
    "timeframe",
    "string",
    "info",
    "file",
    "graphics",
    "gui",
    "matrix",
    "speech",
    "cbi",
    "misc",
]
Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _check_time_zone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (KeyError, ValueError, OSError):
        raise ValueError(f"unknown time zone {value!r}") from None
    return value


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Param(Record):
    name: Identifier
    type: ParamType
    optional: bool


class FunctionRecord(Record):
    name: Identifier
    category: Category
    returns: ReturnType
    params: list[Param]
    # True when any number of further arguments may follow `params` (printf).
    variadic: bool = False
    # In our own words. May be left out until one is written.
    description: Text | None = None
    doc_url: Text
    # AmiBroker version that introduced the function, as "major.minor".
    since: (
        Annotated[
            str, BeforeValidator(_must_be_text), StringConstraints(pattern=r"^[0-9]+\.[0-9]+$")
        ]
        | None
    ) = None

    @field_validator("doc_url")
    @classmethod
    def _doc_url_is_official(cls, value: str) -> str:
        if not value.startswith(DOC_URL_PREFIX):
            raise ValueError(f"must start with {DOC_URL_PREFIX}")
        return value

    @model_validator(mode="after")
    def _check_params(self) -> "FunctionRecord":
        seen: set[str] = set()
        optional_seen = False
        for param in self.params:
            key = param.name.lower()
            if key in seen:
                raise ValueError(f"duplicate parameter {param.name!r}")
            seen.add(key)
            if param.optional:
                optional_seen = True
            elif optional_seen:
                raise ValueError(f"required parameter {param.name!r} follows an optional one")
        return self

    @property
    def min_args(self) -> int:
        return sum(1 for param in self.params if not param.optional)

    @property
    def max_args(self) -> int | None:
        """The most arguments a call may have, or None when there is no limit."""
        return None if self.variadic else len(self.params)


class BuiltinRecord(Record):
    name: Identifier
    kind: Literal["variable", "constant"]
    type: ValueType
    description: Text
    aliases: list[Identifier] = []

    @model_validator(mode="after")
    def _check_aliases(self) -> "BuiltinRecord":
        seen = {self.name.lower()}
        for alias in self.aliases:
            key = alias.lower()
            if key in seen:
                raise ValueError(f"alias {alias!r} repeats the name or another alias")
            seen.add(key)
        return self


class Session(Record):
    name: Identifier
    open: TimeOfDay
    close: TimeOfDay
    days: list[Day] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_times(self) -> "Session":
        if self.close <= self.open:
            raise ValueError("close must be after open")
        if len(set(self.days)) != len(self.days):
            raise ValueError("days lists a day twice")
        return self


class DstRule(Record):
    """A session close that moves with daylight saving somewhere else.

    While daylight saving in `reference_timezone` matches `dst_active`,
    the session named by `session` closes at `close` instead of at its
    own `close`.
    """

    session: Identifier
    reference_timezone: Text
    dst_active: bool
    close: TimeOfDay

    _reference_timezone_exists = field_validator("reference_timezone")(_check_time_zone)


class Market(Record):
    id: Annotated[
        str, BeforeValidator(_must_be_text), StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")
    ]
    name: Text
    exchange: Text
    timezone: Text
    sessions: list[Session] = Field(min_length=1)
    dst_rules: list[DstRule]
    # Required, but may be empty: null means nobody has checked the times yet.
    last_verified: datetime.date | None

    _timezone_exists = field_validator("timezone")(_check_time_zone)

    @model_validator(mode="after")
    def _check_sessions_and_rules(self) -> "Market":
        sessions = {session.name: session for session in self.sessions}
        if len(sessions) != len(self.sessions):
            raise ValueError("duplicate session name")

        seasons: dict[tuple[str, str], list[bool]] = {}
        for rule in self.dst_rules:
            session = sessions.get(rule.session)
            if session is None:
                raise ValueError(f"dst_rules: no session named {rule.session!r}")
            if rule.close <= session.open:
                raise ValueError(f"dst_rules: close for {rule.session!r} must be after its open")
            seasons.setdefault((rule.session, rule.reference_timezone), []).append(rule.dst_active)
        for (session_name, _), flags in seasons.items():
            if sorted(flags) != [False, True]:
                raise ValueError(
                    f"dst_rules: session {session_name!r} needs one rule for each season "
                    "(dst_active true and dst_active false)"
                )
        return self


# Notes: the text the copilot retrieves. All of it is written for this
# project, in our own words.

TIMEFRAMES = (
    "1min",
    "3min",
    "5min",
    "10min",
    "15min",
    "30min",
    "hourly",
    "daily",
    "weekly",
    "monthly",
)
Timeframe = Literal[
    "1min", "3min", "5min", "10min", "15min", "30min", "hourly", "daily", "weekly", "monthly"
]
SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
Slug = Annotated[str, BeforeValidator(_must_be_text), StringConstraints(pattern=SLUG_PATTERN)]


def _must_not_be_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


Body = Annotated[str, BeforeValidator(_must_be_text), AfterValidator(_must_not_be_blank)]


class MistakeRecord(Record):
    """A known AFL mistake, with a wrong and a right version of the code."""

    id: Slug
    title: Text
    # The checker rule that catches it, or null when only the AI review can.
    checker_rule: Text | None
    # The timeframe the two examples are written for.
    timeframe: Timeframe = "daily"
    explanation: Body
    bad_example: Body
    good_example: Body
    tags: list[Slug] = []


class ConceptNote(Record):
    id: Slug
    title: Text
    content: Body
    tags: list[Slug] = []


class ExampleRecord(Record):
    """A generic strategy written for this project. Never a private one."""

    id: Slug
    title: Text
    timeframe: Timeframe
    market: Text
    description: Body
    code: Body
    tags: list[Slug] = []


class ErrorNote(Record):
    """Our own note on an AmiBroker error: what it means and how to fix it."""

    id: Slug
    # AmiBroker's error number, or null when the error has none.
    code: int | None
    title: Text
    explanation: Body
    fix: Body
    tags: list[Slug] = []
