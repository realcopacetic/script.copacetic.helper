# author: realcopacetic

from dataclasses import dataclass

from resources.lib.shared.utilities import to_int


@dataclass(frozen=True, slots=True)
class ArtworkIdentity:
    """
    Scoped item identity for the artwork currency handshake.
    Wire format is scope/pos/dbid/visit; the scope segment is omitted
    entirely when empty, all other fields serialise even when empty.
    """

    scope: str = ""
    pos: int | None = None
    dbid: str = ""
    visit: str = ""

    @classmethod
    def parse(cls, value: str) -> "ArtworkIdentity":
        """
        Parse a wire-format identity; a value without "/" yields an empty identity.
        Mirrors the historical rule: the leading segment is the scope.

        :param value: Serialised identity string.
        :return: Parsed identity (fields empty where absent).
        """
        if "/" not in value:
            return cls()
        scope, _, rest = value.partition("/")
        pos, _, rest = rest.partition("/")
        dbid, _, visit = rest.partition("/")
        return cls(scope=scope, pos=to_int(pos, None), dbid=dbid, visit=visit)

    def partial(self, fields: tuple[str, ...]) -> str:
        """
        Serialise the given fields in wire order.
        Scope is skipped when empty; other fields keep their separator slot.

        :param fields: Field names to serialise, in order.
        :return: "/"-joined serialisation.
        """
        segments = []
        for field in fields:
            value = getattr(self, field)
            if field == "scope":
                if value:
                    segments.append(value)
            else:
                segments.append("" if value is None else str(value))
        return "/".join(segments)

    def neighbour(self, offset: int, total: int) -> "ArtworkIdentity":
        """
        Identity at pos+offset; wraps 1-based positions when total > 1.
        dbid and visit do not travel to neighbours.

        :param offset: Position delta (e.g. -1 / +1).
        :param total: Container item count; <= 1 disables wrapping.
        :return: Neighbouring identity with same scope.
        """
        if self.pos is None:
            return ArtworkIdentity(scope=self.scope)
        pos = self.pos + offset
        if total > 1:
            pos = (pos - 1) % total + 1
        return ArtworkIdentity(scope=self.scope, pos=pos)

    def __str__(self) -> str:
        return self.partial(("scope", "pos", "dbid", "visit"))
