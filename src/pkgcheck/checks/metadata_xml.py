import os
from difflib import SequenceMatcher

from lxml import etree
from pkgcore import const as pkgcore_const
from pkgcore.ebuild.atom import MalformedAtom, atom
from snakeoil.osutils import pjoin
from snakeoil.strings import pluralism

from .. import base, results, sources
from . import Check


class _MissingXml(results.Error):
    """Required XML file is missing."""

    def __init__(self, filename, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename

    @property
    def desc(self):
        return f'{self._attr} is missing {self.filename}'


class _BadlyFormedXml(results.Warning):
    """XML isn't well formed."""

    def __init__(self, filename, error, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.error = error

    @property
    def desc(self):
        return f'{self._attr} {self.filename} is not well formed xml: {self.error}'


class _InvalidXml(results.Error):
    """XML fails XML Schema validation."""

    def __init__(self, filename, message, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.message = message

    @property
    def desc(self):
        return f'{self._attr} {self.filename} violates metadata.xsd:\n{self.message}'


class _MetadataXmlInvalidPkgRef(results.Error):
    """metadata.xml <pkg/> references unknown/invalid package."""

    def __init__(self, filename, pkgtext, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.pkgtext = pkgtext

    @property
    def desc(self):
        return (
            f'{self._attr} {self.filename} <pkg/> '
            f'references unknown/invalid package: {self.pkgtext!r}'
        )


class _MetadataXmlInvalidCatRef(results.Error):
    """metadata.xml <cat/> references unknown/invalid category."""

    def __init__(self, filename, cattext, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.cattext = cattext

    @property
    def desc(self):
        return (
            f'{self._attr} {self.filename} <cat/> references '
            f'unknown/invalid category: {self.cattext!r}'
        )


class MaintainerNeeded(results.PackageResult, results.Warning):
    """Package with missing or invalid maintainer-needed comment in metadata.xml."""

    def __init__(self, filename, needed, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.needed = needed

    @property
    def desc(self):
        if not self.needed:
            return f'{self.filename}: missing maintainer-needed comment'
        return f'{self.filename}: invalid maintainer-needed comment'


class MaintainerWithoutProxy(results.PackageResult, results.Warning):
    """Package has a proxied maintainer without a proxy.

    All package maintainers have non-@gentoo.org e-mail addresses. Most likely,
    this means that the package is maintained by a proxied maintainer but there
    is no explicit proxy (developer or project) listed. This means no Gentoo
    developer will be CC-ed on bug reports, and most likely no developer
    oversees the proxied maintainer's activity.
    """

    def __init__(self, filename, maintainers, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.maintainers = tuple(maintainers)

    @property
    def desc(self):
        s = pluralism(self.maintainers)
        maintainers = ', '.join(self.maintainers)
        return f'{self.filename}: proxied maintainer{s} missing proxy dev/project: {maintainers}'


class StaleProxyMaintProject(results.PackageResult, results.Warning):
    """Package lists proxy-maint project but has no proxied maintainers.

    The package explicitly lists proxy-maint@g.o as the only maintainer.
    Most likely, this means that the proxied maintainer has been removed
    but proxy-maint was left over.
    """

    def __init__(self, filename, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename

    @property
    def desc(self):
        return f'{self.filename}: proxy-maint maintainer with no proxies'


class NonexistentProjectMaintainer(results.PackageResult, results.Warning):
    """Package specifying nonexistent project as a maintainer."""

    def __init__(self, filename, emails, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.emails = tuple(emails)

    @property
    def desc(self):
        s = pluralism(self.emails)
        emails = ', '.join(self.emails)
        return f'{self.filename}: nonexistent project maintainer{s}: {emails}'


class WrongMaintainerType(results.PackageResult, results.Warning):
    """A person-type maintainer matches an existing project."""

    def __init__(self, filename, emails, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.emails = tuple(emails)

    @property
    def desc(self):
        s = pluralism(self.emails)
        emails = ', '.join(self.emails)
        return f'{self.filename}: project maintainer{s} with type="person": {emails}'


class PkgMissingMetadataXml(_MissingXml, results.PackageResult):
    """Package is missing metadata.xml."""


class CatMissingMetadataXml(_MissingXml, results.CategoryResult):
    """Category is missing metadata.xml."""


class PkgInvalidXml(_InvalidXml, results.PackageResult):
    """Invalid package metadata.xml."""


class CatInvalidXml(_InvalidXml, results.CategoryResult):
    """Invalid category metadata.xml."""


class PkgBadlyFormedXml(_BadlyFormedXml, results.PackageResult):
    """Badly formed package metadata.xml."""


class CatBadlyFormedXml(_BadlyFormedXml, results.CategoryResult):
    """Badly formed category metadata.xml."""


class PkgMetadataXmlInvalidPkgRef(_MetadataXmlInvalidPkgRef, results.PackageResult):
    """Invalid package reference in package metadata.xml."""


class CatMetadataXmlInvalidPkgRef(_MetadataXmlInvalidPkgRef, results.CategoryResult):
    """Invalid package reference in category metadata.xml."""


class PkgMetadataXmlInvalidCatRef(_MetadataXmlInvalidCatRef, results.PackageResult):
    """Invalid category reference in package metadata.xml."""


class CatMetadataXmlInvalidCatRef(_MetadataXmlInvalidCatRef, results.CategoryResult):
    """Invalid category reference in category metadata.xml."""


class _MetadataXmlIndentation(results.Warning):
    """Inconsistent indentation in metadata.xml file.

    Either all tabs or all spaces should be used, not a mixture of both.
    """

    def __init__(self, filename, lines, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.lines = tuple(lines)

    @property
    def desc(self):
        s = pluralism(self.lines)
        lines = ', '.join(self.lines)
        return f'{self.filename}: metadata.xml has inconsistent indentation on line{s}: {lines}'


class CatMetadataXmlIndentation(_MetadataXmlIndentation, results.CategoryResult):
    """Inconsistent indentation in category metadata.xml file.

    Either all tabs or all spaces should be used, not a mixture of both.
    """


class PkgMetadataXmlIndentation(_MetadataXmlIndentation, results.PackageResult):
    """Inconsistent indentation in package metadata.xml file.

    Either all tabs or all spaces should be used, not a mixture of both.
    """


class _MetadataXmlEmptyElement(results.Warning):
    """Empty element in metadata.xml file."""

    def __init__(self, filename, element, line, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.element = element
        self.line = line

    @property
    def desc(self):
        return f'{self.filename}: empty element {self.element!r} on line {self.line}'


class CatMetadataXmlEmptyElement(_MetadataXmlEmptyElement, results.CategoryResult):
    """Empty element in category metadata.xml file."""


class PkgMetadataXmlEmptyElement(_MetadataXmlEmptyElement, results.PackageResult):
    """Empty element in package metadata.xml file."""


class RedundantLongDescription(results.PackageResult, results.Warning):
    """Package's longdescription element in metadata.xml and DESCRIPTION are interchangeable.

    The longdescription element is for providing extended information that
    doesn't fit in DESCRIPTION.
    """

    def __init__(self, msg, **kwargs):
        super().__init__(**kwargs)
        self.msg = msg

    @property
    def desc(self):
        return self.msg


class _XmlBaseCheck(Check):
    """Base class for metadata.xml scans."""

    schema = None

    misformed_error = None
    invalid_error = None
    missing_error = None

    def __init__(self, *args):
        super().__init__(*args)
        self.repo_base = self.options.target_repo.location
        self.pkgref_cache = {}
        # content validation checks to run after parsing XML doc
        self._checks = tuple(
            getattr(self, x) for x in dir(self) if x.startswith('_check_'))

        # Prefer xsd file from the target repository or its masters, falling
        # back to the file installed with pkgcore.
        for repo in reversed(self.options.target_repo.trees):
            metadata_xsd = pjoin(repo.location, 'metadata', 'xml-schema', 'metadata.xsd')
            if os.path.isfile(metadata_xsd):
                try:
                    self.schema = etree.XMLSchema(etree.parse(metadata_xsd))
                    break
                except etree.XMLSchemaParseError:
                    # ignore invalid xsd files
                    pass
        else:
            metadata_xsd = pjoin(pkgcore_const.DATA_PATH, 'xml-schema', 'metadata.xsd')
            self.schema = etree.XMLSchema(etree.parse(metadata_xsd))

    def _check_doc(self, pkg, loc, doc):
        """Perform additional document structure checks."""
        # find all root descendant elements that are empty
        for el in doc.getroot().iterdescendants():
            if (not el.getchildren() and (el.text is None or not el.text.strip())
                    and not el.tag == 'stabilize-allarches'):
                yield self.empty_element(os.path.basename(loc), el.tag, el.sourceline, pkg=pkg)

        for el in doc.findall('.//cat'):
            c = el.text.strip()
            if c not in self.options.search_repo.categories:
                yield self.catref_error(os.path.basename(loc), c, pkg=pkg)

        for el in doc.findall('.//pkg'):
            p = el.text.strip()
            if p not in self.pkgref_cache:
                try:
                    a = atom(p)
                    found = self.options.search_repo.has_match(a)
                except MalformedAtom:
                    found = False
                self.pkgref_cache[p] = found

            if not self.pkgref_cache[p]:
                yield self.pkgref_error(os.path.basename(loc), p, pkg=pkg)

    def _check_whitespace(self, pkg, loc, doc):
        """Check for indentation consistency."""
        orig_indent = None
        indents = set()
        with open(loc) as f:
            for lineno, line in enumerate(f, 1):
                for i in line[:-len(line.lstrip())]:
                    if i != orig_indent:
                        if orig_indent is None:
                            orig_indent = i
                        else:
                            indents.add(lineno)
        if indents:
            yield self.indent_error(os.path.basename(loc), map(str, sorted(indents)), pkg=pkg)

    @staticmethod
    def _format_lxml_errors(error_log):
        for x in error_log:
            yield f'line {x.line}, col {x.column}: ({x.type_name}) {x.message}'

    def _parse_xml(self, pkg, loc):
        try:
            doc = etree.parse(loc)
        except (IOError, OSError):
            # it's only an error when missing in the main gentoo repo
            if self.options.gentoo_repo:
                yield self.missing_error(os.path.basename(loc), pkg=pkg)
            return
        except etree.XMLSyntaxError as e:
            yield self.misformed_error(os.path.basename(loc), str(e), pkg=pkg)
            return

        # note: while doc is available, do not pass it here as it may
        # trigger undefined behavior due to incorrect structure
        if self.schema is not None and not self.schema.validate(doc):
            message = '\n'.join(self._format_lxml_errors(self.schema.error_log))
            yield self.invalid_error(os.path.basename(loc), message, pkg=pkg)
            return

        # run all post parsing/validation checks
        for check in self._checks:
            yield from check(pkg, loc, doc)

    def feed(self, pkgset):
        pkg = pkgset[0]
        loc = self._get_xml_location(pkg)
        yield from self._parse_xml(pkg, loc)


class PackageMetadataXmlCheck(_XmlBaseCheck):
    """Package level metadata.xml scans."""

    _source = sources.PackageRepoSource
    misformed_error = PkgBadlyFormedXml
    invalid_error = PkgInvalidXml
    missing_error = PkgMissingMetadataXml
    catref_error = PkgMetadataXmlInvalidCatRef
    pkgref_error = PkgMetadataXmlInvalidPkgRef
    indent_error = PkgMetadataXmlIndentation
    empty_element = PkgMetadataXmlEmptyElement

    known_results = frozenset([
        PkgBadlyFormedXml, PkgInvalidXml, PkgMissingMetadataXml,
        PkgMetadataXmlInvalidPkgRef, PkgMetadataXmlInvalidCatRef,
        PkgMetadataXmlIndentation, PkgMetadataXmlEmptyElement, MaintainerNeeded,
        MaintainerWithoutProxy, StaleProxyMaintProject, RedundantLongDescription,
        NonexistentProjectMaintainer, WrongMaintainerType,
    ])

    def _check_maintainers(self, pkg, loc, doc):
        """Validate maintainers in package metadata for the gentoo repo."""
        if self.options.gentoo_repo:
            maintainer_needed = any(
                c.text.strip() == 'maintainer-needed' for c in doc.xpath('//comment()'))
            if pkg.maintainers:
                # check for invalid maintainer-needed comment
                if maintainer_needed:
                    yield MaintainerNeeded(os.path.basename(loc), maintainer_needed, pkg=pkg)
                # check proxy maintainers
                if not any(m.email.endswith('@gentoo.org') for m in pkg.maintainers):
                    maintainers = sorted(map(str, pkg.maintainers))
                    yield MaintainerWithoutProxy(
                        os.path.basename(loc), maintainers, pkg=pkg)
                elif (all(m.email.endswith('@gentoo.org') for m in pkg.maintainers) and
                      'proxy-maint@gentoo.org' in pkg.maintainers):
                    yield StaleProxyMaintProject(os.path.basename(loc), pkg=pkg)
            elif not maintainer_needed:
                # check for missing maintainer-needed comment
                yield MaintainerNeeded(os.path.basename(loc), maintainer_needed, pkg=pkg)

            # check maintainer validity
            if projects := set(pkg.repo.projects_xml.projects):
                nonexistent = []
                wrong_maintainers = []
                for m in pkg.maintainers:
                    if m.maint_type == 'project' and m.email not in projects:
                        nonexistent.append(m.email)
                    elif m.maint_type == 'person' and m.email in projects:
                        wrong_maintainers.append(m.email)
                if nonexistent:
                    yield NonexistentProjectMaintainer(
                        os.path.basename(loc), sorted(nonexistent), pkg=pkg)
                if wrong_maintainers:
                    yield WrongMaintainerType(
                        os.path.basename(loc), sorted(wrong_maintainers), pkg=pkg)

    def _check_longdescription(self, pkg, loc, doc):
        if pkg.longdescription is not None:
            match_ratio = SequenceMatcher(None, pkg.description, pkg.longdescription).ratio()
            if match_ratio > 0.75:
                msg = 'metadata.xml longdescription closely matches DESCRIPTION'
                yield RedundantLongDescription(msg, pkg=pkg)
            elif len(pkg.longdescription) < 100:
                msg = 'metadata.xml longdescription is too short'
                yield RedundantLongDescription(msg, pkg=pkg)

    def _get_xml_location(self, pkg):
        """Return the metadata.xml location for a given package."""
        return pjoin(os.path.dirname(pkg.ebuild.path), 'metadata.xml')


class CategoryMetadataXmlCheck(_XmlBaseCheck):
    """Category level metadata.xml scans."""

    _source = (sources.CategoryRepoSource, (), (('source', sources.RawRepoSource),))
    misformed_error = CatBadlyFormedXml
    invalid_error = CatInvalidXml
    missing_error = CatMissingMetadataXml
    catref_error = CatMetadataXmlInvalidCatRef
    pkgref_error = CatMetadataXmlInvalidPkgRef
    indent_error = CatMetadataXmlIndentation
    empty_element = CatMetadataXmlEmptyElement

    known_results = frozenset([
        CatBadlyFormedXml, CatInvalidXml, CatMissingMetadataXml,
        CatMetadataXmlInvalidPkgRef, CatMetadataXmlInvalidCatRef,
        CatMetadataXmlIndentation, CatMetadataXmlEmptyElement,
    ])

    def _get_xml_location(self, pkg):
        """Return the metadata.xml location for a given package's category."""
        return pjoin(self.repo_base, pkg.category, 'metadata.xml')
