from snakeoil.demandload import demand_compile_regexp
from snakeoil.strings import pluralism as _pl

from .. import base

demand_compile_regexp('indent_regexp', '^\t* \t+')


class _Whitespace(base.VersionedResult, base.Warning):

    @property
    def lines_str(self):
        return f"line{_pl(self.lines)}: {', '.join(str(x) for x in self.lines)}"


class WhitespaceFound(_Whitespace):
    """Leading or trailing whitespace found."""

    def __init__(self, pkg, leadtrail, lines):
        super().__init__(pkg)
        self.lines = tuple(lines)
        self.leadtrail = leadtrail

    @property
    def short_desc(self):
        return f"ebuild has {self.leadtrail} whitespace on {self.lines_str}"


class WrongIndentFound(_Whitespace):
    """Incorrect indentation whitespace found."""

    def __init__(self, pkg, lines):
        super().__init__(pkg)
        self.lines = tuple(lines)

    @property
    def short_desc(self):
        return f"ebuild has whitespace in indentation on {self.lines_str}"


class DoubleEmptyLine(_Whitespace):
    """Unneeded blank lines found."""

    def __init__(self, pkg, lines):
        super().__init__(pkg)
        self.lines = tuple(lines)

    @property
    def short_desc(self):
        return f"ebuild has unneeded empty {self.lines_str}"


class TrailingEmptyLine(base.VersionedResult, base.Warning):
    """Unneeded trailing blank lines found."""

    short_desc = "ebuild has trailing blank line(s)"


class NoFinalNewline(base.VersionedResult, base.Warning):
    """Ebuild's last line does not have a final newline."""

    short_desc = "ebuild lacks an ending newline"


class WhitespaceCheck(base.Check):
    """Scan ebuild for useless whitespace."""

    feed_type = base.ebuild_feed
    known_results = (
        WhitespaceFound, WrongIndentFound, DoubleEmptyLine,
        TrailingEmptyLine, NoFinalNewline)

    def feed(self, entry):
        pkg, lines = entry
        lastlineempty = False
        trailing = []
        leading = []
        indent = []
        double_empty = []

        for lineno, line in enumerate(lines, 1):
            if line != '\n':
                lastlineempty = False
                if line[-2:-1] == ' ' or line[-2:-1] == '\t':
                    trailing.append(lineno)
                elif line[0] == ' ':
                    leading.append(lineno)
                if indent_regexp.match(line):
                    indent.append(lineno)
            elif lastlineempty:
                double_empty.append(lineno)
            else:
                lastlineempty = True
        if trailing:
            yield WhitespaceFound(pkg, "trailing", trailing)
        if leading:
            yield WhitespaceFound(pkg, "leading", leading)
        if indent:
            yield WrongIndentFound(pkg, indent)
        if double_empty:
            yield DoubleEmptyLine(pkg, double_empty)
        if lastlineempty:
            yield TrailingEmptyLine(pkg)

        # Dealing with empty ebuilds is just paranoia
        if lines and not lines[-1].endswith('\n'):
            yield NoFinalNewline(pkg)
