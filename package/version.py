import re

VERSION_REGEX = r"^(\d+)(.(\d+))?(.(\d+))?(-(.+))?$"


class Version(str):
    def __init__(self, version_string: str | None):
        self.__version_string = version_string
        self.__match = re.match(VERSION_REGEX, version_string) if version_string is not None else None
        self.major = int(self.__match.group(1)) if self.__match and self.__match.group(1) is not None else None
        self.minor = int(self.__match.group(3)) if self.__match and self.__match.group(3) is not None else None
        self.patch = int(self.__match.group(5)) if self.__match and self.__match.group(5) is not None else None
        self.preview = self.__match.group(7) if self.__match and self.__match.group(7) is not None else None

    def __repr__(self):
        return self.__version_string if self.__version_string is not None else "None"

    def __le__(self, other_version):
        other = other_version if isinstance(other_version, Version) else Version(other_version) if type(other_version) == str else None
        if not self.exists or other is None or not other.exists:
            return False

        return self == other or self < other

    def __ge__(self, other_version):
        other = other_version if isinstance(other_version, Version) else Version(other_version) if type(other_version) == str else None
        if not self.exists or other is None or not other.exists:
            return False

        return self == other or self > other

    def __ne__(self, other_version):
        other = other_version if isinstance(other_version, Version) else Version(other_version) if type(other_version) == str else None
        if not self.exists or other is None or not other.exists:
            return False

        return self.__version_string != other.__version_string

    def __eq__(self, other_version):
        other = other_version if isinstance(other_version, Version) else Version(other_version) if type(other_version) == str else None
        if not self.exists or other is None or not other.exists:
            return False

        return self.__version_string == other.__version_string

    def __lt__(self, other_version):
        other = other_version if isinstance(other_version, Version) else Version(other_version) if type(other_version) == str else None
        if not self.exists or other is None or not other.exists:
            return False

        if self.major is None or other.major is None:
            # This should never happen since it will not match unless this exists
            return False
        if self.major != other.major:
            return self.major < other.major

        if self.minor != other.minor:
            if self.minor is None:
                return False
            if other.minor is None:
                return True
            return self.minor < other.minor

        if self.patch != other.patch:
            if self.patch is None:
                return False
            if other.patch is None:
                return True
            return self.patch < other.patch

        if self.preview != other.preview:
            if self.preview is None:
                return True
            if other.preview is None:
                return False

        return False

    def __gt__(self, other_version):
        other = other_version if isinstance(other_version, Version) else Version(other_version) if type(other_version) == str else None
        if not self.exists or other is None or not other.exists:
            return False

        if self.major is None or other.major is None:
            # This should never happen since it will not match unless this exists
            return False
        if self.major != other.major:
            return self.major > other.major

        if self.minor != other.minor:
            if self.minor is None:
                return True
            if other.minor is None:
                return False
            return self.minor > other.minor

        if self.patch != other.patch:
            if self.patch is None:
                return True
            if other.patch is None:
                return False
            return self.patch > other.patch

        if self.preview != other.preview:
            if self.preview is None:
                return False
            if other.preview is None:
                return True

        return False

    @property
    def exists(self):
        return self.__match is not None
