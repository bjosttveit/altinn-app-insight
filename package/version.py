from __future__ import annotations

from typing import Any

import re

VERSION_REGEX = r"^(\d+)(.(\d+))?(.(\d+))?(-(.+))?$"


class NullableInt:
    def __init__(self, value: int | str | None):
        if isinstance(value, str):
            self.value = int(value)
        else:
            self.value = value

    @staticmethod
    def from_value(value: Any):
        if isinstance(value, NullableInt):
            return value
        if isinstance(value, int) or isinstance(value, str):
            return NullableInt(value)
        return NullableInt(None)

    @property
    def exists(self):
        return self.value is not None

    def __repr__(self):
        return str(self.value)

    def __le__(self, other_value):
        other = NullableInt.from_value(other_value)
        return self == other or self < other

    def __ge__(self, other_value):
        other = NullableInt.from_value(other_value)
        return self == other or self > other

    def __eq__(self, other_value):
        other = NullableInt.from_value(other_value)
        return self.value == other.value

    def __ne__(self, other_value):
        other = NullableInt.from_value(other_value)
        return self.value != other.value

    """ Assuming that None is the smallest value """

    def __lt__(self, other_value):
        other = NullableInt.from_value(other_value)
        if self.value is None or other.value is None:
            return other.exists
        return self.value < other.value

    def __gt__(self, other_value):
        other = NullableInt.from_value(other_value)
        if self.value is None or other.value is None:
            return self.exists
        return self.value > other.value


class Version(str):
    def __init__(self, version_string: str | None):
        self.__version_string = version_string
        self.__match = re.match(VERSION_REGEX, version_string) if version_string is not None else None
        self.major = NullableInt(self.__match.group(1) if self.__match else None)
        self.minor = NullableInt(self.__match.group(3) if self.__match else None)
        self.patch = NullableInt(self.__match.group(5) if self.__match else None)
        self.preview = self.__match.group(7) if self.__match else None

    def __repr__(self):
        return self.__version_string if self.__version_string is not None else "None"

    @staticmethod
    def from_value(value: Any):
        if isinstance(value, Version):
            return value
        if isinstance(value, str):
            return Version(value)
        return Version(None)

    def __le__(self, other_value):
        other = Version.from_value(other_value)
        return self == other or self < other

    def __ge__(self, other_value):
        other = Version.from_value(other_value)
        return self == other or self > other

    def __ne__(self, other_value):
        other = Version.from_value(other_value)
        return self.__version_string != other.__version_string

    def __eq__(self, other_value):
        other = Version.from_value(other_value)
        return self.__version_string == other.__version_string

    """ Assuming that None is the smallest value, and that missing components makes it bigger, i.e. 4 > 4.18 """

    def __lt__(self, other_value):
        other = Version.from_value(other_value)
        if not self.exists or not other.exists:
            return other.exists

        if self.major != other.major:
            return self.major < other.major

        if self.minor != other.minor:
            if not self.minor.exists:
                return False
            if not other.minor.exists:
                return True
            return self.minor < other.minor

        if self.patch != other.patch:
            if not self.patch.exists:
                return False
            if not other.patch.exists:
                return True
            return self.patch < other.patch

        if self.preview != other.preview:
            if self.preview is None:
                return False
            if other.preview is None:
                return True

        return False

    def __gt__(self, other_value):
        other = Version.from_value(other_value)
        if not self.exists or not other.exists:
            return self.exists

        if self.major != other.major:
            return self.major > other.major

        if self.minor != other.minor:
            if not self.minor.exists:
                return True
            if not other.minor.exists:
                return False
            return self.minor > other.minor

        if self.patch != other.patch:
            if not self.patch.exists:
                return True
            if not other.patch.exists:
                return False
            return self.patch > other.patch

        if self.preview != other.preview:
            if self.preview is None:
                return True
            if other.preview is None:
                return False

        return False

    @property
    def exists(self):
        return self.__match is not None
