#
# This file is part of translate.
#
# translate is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# translate is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, see <http://www.gnu.org/licenses/>.

"""
Create a terminology file by reading a set of .po or .pot files to produce a pootle-terminology.pot.

See: http://docs.translatehouse.org/projects/translate-toolkit/en/latest/commands/poterminology.html
for examples and usage instructions.
"""

import contextlib
import logging
import os
import re
import sys
from operator import itemgetter

from translate.lang import factory as lang_factory
from translate.misc import file_discovery, optrecurse
from translate.storage import factory, po

logger = logging.getLogger(__name__)


def create_termunit(
    term, unit, targets, locations, sourcenotes, transnotes, filecounts
):
    termunit = po.pounit(term)
    if unit is not None:
        termunit.merge(unit, overwrite=False, comments=False)
    if len(targets.keys()) > 1:
        txt = "; ".join(
            "{} {{{}}}".format(target, ", ".join(files))
            for target, files in targets.items()
        )
        if termunit.target.find("};") < 0:
            termunit.target = txt
            termunit.markfuzzy()
        else:
            # if annotated multiple terms already present, keep as-is
            termunit.addnote(txt, "translator")
    for location in locations:
        termunit.addlocation(location)
    for sourcenote in sourcenotes:
        termunit.addnote(sourcenote, "developer")
    for transnote in transnotes:
        termunit.addnote(transnote, "translator")
    for filename, count in filecounts.items():
        termunit.addnote("(poterminology) %s (%d)\n" % (filename, count), "translator")
    return termunit


class TerminologyExtractor:
    def __init__(
        self,
        foldtitle=True,
        ignorecase=False,
        accelchars="",
        termlength=3,
        sourcelanguage="en",
        invert=False,
        stopfile=None,
    ):
        self.foldtitle = foldtitle
        self.ignorecase = ignorecase
        self.accelchars = accelchars
        self.termlength = termlength

        self.sourcelanguage = sourcelanguage
        self.invert = invert

        self.stopwords = {}
        self.stoprelist = []
        self.stopfoldtitle = True
        self.stopignorecase = False

        if stopfile is None:
            with contextlib.suppress(Exception):
                stopfile = file_discovery.get_abs_data_filename(
                    f"stoplist-{self.sourcelanguage}"
                )
        self.stopfile = stopfile
        self.parse_stopword_file()

        # handles c-format and python-format
        self.formatpat = re.compile(
            r"%(?:\([^)]+\)|[0-9]+\$)?[-+#0]*[0-9.*]*(?:[hlLzjt][hl])?[EFGXc-ginoprsux]"
        )
        # handles XML/HTML elements (<foo>text</foo> => text)
        self.xmlelpat = re.compile(r"<(?:![\[-]|[/?]?[A-Za-z_:])[^>]*>")
        # handles XML/HTML entities (&#32; &#x20; &amp; &my_entity;)
        self.xmlentpat = re.compile(
            r"&(?:#(?:[0-9]+|x[0-9a-f]+)|[a-z_:][\w.-:]*);",
            flags=re.UNICODE | re.IGNORECASE,
        )

        self.units = 0
        self.glossary = {}

    def parse_stopword_file(self):
        actions = {
            "+": frozenset(),
            ":": frozenset(["skip"]),
            "<": frozenset(["phrase"]),
            "=": frozenset(["word"]),
            ">": frozenset(["word", "skip"]),
            "@": frozenset(["word", "phrase"]),
        }

        with open(self.stopfile) as stopfile:
            line = 0
            try:
                for stopline in stopfile:
                    line += 1
                    stoptype = stopline[0]
                    if stoptype in {"#", "\n"}:
                        continue
                    if stoptype == "!":
                        if stopline[1] == "C":
                            self.stopfoldtitle = False
                            self.stopignorecase = False
                        elif stopline[1] == "F":
                            self.stopfoldtitle = True
                            self.stopignorecase = False
                        elif stopline[1] == "I":
                            self.stopignorecase = True
                        else:
                            logger.warning(
                                "%s:%d - bad case mapping directive",
                                self.stopfile,
                                line,
                            )
                    elif stoptype == "/":
                        self.stoprelist.append(re.compile(stopline[1:-1] + "$"))
                    else:
                        self.stopwords[stopline[1:-1]] = actions[stoptype]
            except KeyError as character:
                logger.warning(
                    "%s:%d - bad stopword entry starts with '%s'",
                    self.stopfile,
                    line,
                    str(character),
                )
                logger.warning(
                    "%s:%d all lines after error ignored", self.stopfile, line + 1
                )

    def clean(self, string):
        """Returns the cleaned string that contains the text to be matched."""
        for accelerator in self.accelchars:
            string = string.replace(accelerator, "")
        string = self.formatpat.sub(" ", string)
        string = self.xmlelpat.sub(" ", string)
        string = self.xmlentpat.sub(" ", string)
        return string.strip()

    def stopmap(self, word):
        """Return case-mapped stopword for input word."""
        if self.stopignorecase or (self.stopfoldtitle and word.istitle()):
            word = word.lower()
        return word

    def stopword(self, word, defaultset=frozenset()):
        """Return stoplist frozenset for input word."""
        return self.stopwords.get(self.stopmap(word), defaultset)

    def addphrases(self, words, skips, translation, partials=True):
        """Adds (sub)phrases with non-skipwords and more than one word."""
        if (
            len(words) > skips + 1
            and "skip" not in self.stopword(words[0])
            and "skip" not in self.stopword(words[-1])
        ):
            self.glossary.setdefault(" ".join(words), []).append(translation)
        if partials:
            part = list(words)
            while len(part) > 2:
                if "skip" in self.stopword(part.pop()):
                    skips -= 1
                if (
                    len(part) > skips + 1
                    and "skip" not in self.stopword(part[0])
                    and "skip" not in self.stopword(part[-1])
                ):
                    self.glossary.setdefault(" ".join(part), []).append(translation)

    def processunits(self, units, fullinputpath):
        sourcelang = lang_factory.getlanguage(self.sourcelanguage)
        rematchignore = frozenset(("word", "phrase"))
        defaultignore = frozenset()
        for unit in units:
            self.units += 1
            if unit.isheader():
                continue
            if not self.invert:
                source = self.clean(unit.source)
                target = self.clean(unit.target)
            else:
                target = self.clean(unit.source)
                source = self.clean(unit.target)
            if len(source) <= 1:
                continue
            for sentence in sourcelang.sentences(source):
                words = []
                skips = 0
                for word in sourcelang.words(sentence):
                    stword = self.stopmap(word)
                    if self.ignorecase or (self.foldtitle and word.istitle()):
                        word = word.lower()
                    ignore = defaultignore
                    if stword in self.stopwords:
                        ignore = self.stopwords[stword]
                    else:
                        for stopre in self.stoprelist:
                            if stopre.match(stword) is not None:
                                ignore = rematchignore
                                break
                    translation = (source, target, unit, fullinputpath)
                    if "word" not in ignore:
                        # reduce plurals
                        root = word
                        if (
                            len(word) > 3
                            and word[-1] == "s"
                            and word[0:-1] in self.glossary
                        ):
                            root = word[0:-1]
                        elif len(root) > 2 and root + "s" in self.glossary:
                            self.glossary[root] = self.glossary.pop(root + "s")
                        self.glossary.setdefault(root, []).append(translation)
                    if self.termlength > 1:
                        if "phrase" in ignore:
                            # add trailing phrases in previous words
                            while len(words) > 2:
                                if "skip" in self.stopword(words.pop(0)):
                                    skips -= 1
                                self.addphrases(words, skips, translation)
                            words = []
                            skips = 0
                        else:
                            words.append(word)
                            if "skip" in ignore:
                                skips += 1
                            if len(words) > self.termlength + skips:
                                while len(words) > self.termlength + skips:
                                    if "skip" in self.stopword(words.pop(0)):
                                        skips -= 1
                                self.addphrases(words, skips, translation)
                            else:
                                self.addphrases(
                                    words, skips, translation, partials=False
                                )
                if self.termlength > 1:
                    # add trailing phrases in sentence after reaching end
                    while self.termlength > 1 and len(words) > 2:
                        if "skip" in self.stopword(words.pop(0)):
                            skips -= 1
                        self.addphrases(words, skips, translation)

    def extract_terms(
        self,
        create_termunit=create_termunit,
        inputmin=1,
        fullmsgmin=1,
        substrmin=2,
        locmin=2,
    ):
        terms = {}
        locre = re.compile(r":[0-9]+$")
        logger.info("%d terms from %d units", len(self.glossary), self.units)
        for term, translations in self.glossary.items():
            if len(translations) <= 1:
                continue
            filecounts = {}
            sources = set()
            locations = set()
            sourcenotes = set()
            transnotes = set()
            targets = {}
            fullmsg = False
            bestunit = None
            for source, target, unit, filename in translations:
                sources.add(source)
                filecounts[filename] = filecounts.setdefault(filename, 0) + 1
                # FIXME: why reclean source and target?!
                if term.lower() == self.clean(unit.source).lower():
                    fullmsg = True
                    target = self.clean(unit.target)
                    if self.ignorecase or (self.foldtitle and target.istitle()):
                        target = target.lower()
                    unit.target = target
                    if target:
                        targets.setdefault(target, []).append(filename)
                    if term.lower() == unit.source.strip().lower():
                        sourcenotes.add(unit.getnotes("source code"))
                        transnotes.add(unit.getnotes("translator"))
                    unit.source = term
                    bestunit = unit
                # FIXME: figure out why we did a merge to begin with
                # termunit.merge(unit, overwrite=False, comments=False)
                locations.update(locre.sub("", loc) for loc in unit.getlocations())

            numsources = len(sources)
            numfiles = len(filecounts)
            numlocs = len(locations)
            if numfiles < inputmin or 0 < numlocs < locmin:
                continue
            if fullmsg:
                if numsources < fullmsgmin:
                    continue
            elif numsources < substrmin:
                continue

            locmax = 2 * locmin
            if numlocs > locmax:
                locations = list(locations)[0:locmax]
                locations.append(
                    "(poterminology) %d more locations" % (numlocs - locmax)
                )

            termunit = create_termunit(
                term, bestunit, targets, locations, sourcenotes, transnotes, filecounts
            )
            terms[term] = ((10 * numfiles) + numsources, termunit)
        return terms

    sortorders_default = ["frequency", "dictionary", "length"]

    def filter_terms(self, terms, nonstopmin=1, sortorders=sortorders_default):
        """Reduce subphrases from extracted terms."""
        # reduce subphrase
        termlist = sorted(terms.keys(), key=len)
        logger.info("%d terms after thresholding", len(termlist))
        for term in termlist:
            words = term.split()
            nonstop = [word for word in words if not self.stopword(word)]
            if len(nonstop) < nonstopmin and len(nonstop) != len(words):
                del terms[term]
                continue
            if len(words) <= 2:
                continue
            while len(words) > 2:
                words.pop()
                if terms[term][0] == terms.get(" ".join(words), [0])[0]:
                    del terms[" ".join(words)]
            words = term.split()
            while len(words) > 2:
                words.pop(0)
                if terms[term][0] == terms.get(" ".join(words), [0])[0]:
                    del terms[" ".join(words)]
        logger.info("%d terms after subphrase reduction", len(terms.keys()))
        termitems = list(terms.values())
        if sortorders is None:
            sortorders = self.sortorders_default
        while len(sortorders) > 0:
            order = sortorders.pop()
            if order == "frequency":
                termitems.sort(key=itemgetter(0), reverse=True)
            elif order == "dictionary":
                termitems.sort(key=lambda x: x[1].source.lower())
            elif order == "length":
                termitems.sort(key=lambda x: x[1].source)
            else:
                logger.warning("unknown sort order %s", order)
        return termitems


class TerminologyOptionParser(optrecurse.RecursiveOptionParser):
    """a specialized Option Parser for the terminology tool..."""

    def parse_args(self, args=None, values=None):
        """Parses the command line options, handling implicit input/output args."""
        (options, args) = optrecurse.optparse.OptionParser.parse_args(
            self, args, values
        )
        # some intelligence as to what reasonable people might give on the command line
        if args and not options.input:
            if not options.output and not options.update and len(args) > 1:
                options.input = args[:-1]
                args = args[-1:]
            else:
                options.input = args
                args = []
        # don't overwrite last freestanding argument file, to avoid accidents
        # due to shell wildcard expansion
        if args and not options.output and not options.update:
            if os.path.lexists(args[-1]) and not os.path.isdir(args[-1]):
                self.error(
                    f"To overwrite {args[-1]}, specify it with -o/--output or -u/--update"
                )
            options.output = args[-1]
            args = args[:-1]
        if options.output and options.update:
            self.error("You cannot use both -u/--update and -o/--output")
        if args:
            self.error(
                "You have used an invalid combination of -i/--input, -o/--output, -u/--update and freestanding args"
            )
        if not options.input:
            self.error("No input file or directory was specified")
        if isinstance(options.input, list) and len(options.input) == 1:
            options.input = options.input[0]
            if options.inputmin is None:
                options.inputmin = 1
        elif not isinstance(options.input, list) and not os.path.isdir(options.input):
            if options.inputmin is None:
                options.inputmin = 1
        elif options.inputmin is None:
            options.inputmin = 2
        if options.update:
            options.output = options.update
            if isinstance(options.input, list):
                options.input.append(options.update)
            elif options.input:
                options.input = [options.input, options.update]
            else:
                options.input = options.update
        if not options.output:
            options.output = "pootle-terminology.pot"
        return (options, args)

    def set_usage(self, usage=None):
        """Sets the usage string - if usage not given, uses getusagestring for each option."""
        if usage is None:
            self.usage = (
                "%prog "
                + " ".join(self.getusagestring(option) for option in self.option_list)
                + "\n  input directory is searched for PO files, terminology PO file is output file"
            )
        else:
            super().set_usage(usage)

    def run(self):
        """Parses the arguments, and runs recursiveprocess with the resulting options."""
        self.files = 0
        options, _args = self.parse_args()
        self.extractor = TerminologyExtractor(
            foldtitle=options.foldtitle,
            ignorecase=options.ignorecase,
            accelchars=options.accelchars,
            termlength=options.termlength,
            sourcelanguage=options.sourcelanguage,
            invert=options.invert,
            stopfile=options.stopfile,
        )
        self.recursiveprocess(options)

    def recursiveprocess(self, options):
        """Recurse through directories and process files."""
        if self.isrecursive(options.input, "input") and getattr(
            options, "allowrecursiveinput", True
        ):
            if isinstance(options.input, list):
                inputfiles = self.recurseinputfilelist(options)
            else:
                inputfiles = self.recurseinputfiles(options)
        elif options.input:
            inputfiles = [os.path.basename(options.input)]
            options.input = os.path.dirname(options.input)
        else:
            inputfiles = [options.input]
        if os.path.isdir(options.output):
            options.output = os.path.join(options.output, "pootle-terminology.pot")

        progress_bar = optrecurse.ProgressBar(options.progress, inputfiles)
        for inputpath in inputfiles:
            self.files += 1
            fullinputpath = self.getfullinputpath(options, inputpath)
            success = True
            try:
                self.processfile(None, options, fullinputpath)
            except Exception:
                self.warning(
                    f"Error processing: input {fullinputpath}",
                    options,
                    sys.exc_info(),
                )
                success = False
            progress_bar.report_progress(inputpath, success)
        self.outputterminology(options)

    def processfile(self, fileprocessor, options, fullinputpath):
        """Process an individual file."""
        inputfile = self.openinputfile(options, fullinputpath)
        inputfile = factory.getobject(inputfile)
        self.extractor.processunits(inputfile.units, fullinputpath)

    def outputterminology(self, options):
        """Saves the generated terminology glossary."""
        termfile = po.pofile()
        logger.info("scanned %d files", self.files)
        terms = self.extractor.extract_terms(
            inputmin=options.inputmin,
            fullmsgmin=options.fullmsgmin,
            substrmin=options.substrmin,
            locmin=options.locmin,
        )
        termitems = self.extractor.filter_terms(
            terms, nonstopmin=options.nonstopmin, sortorders=options.sortorders
        )
        for count, unit in termitems:
            termfile.units.append(unit)
        with open(options.output, "wb") as fh:
            termfile.serialize(fh)


def fold_case_option(option, opt_str, value, parser):
    parser.values.ignorecase = False
    parser.values.foldtitle = True


def preserve_case_option(option, opt_str, value, parser):
    parser.values.ignorecase = parser.values.foldtitle = False


def main():
    formats = {"po": ("po", None), "pot": ("pot", None), None: ("po", None)}
    parser = TerminologyOptionParser(formats)

    parser.add_option(
        "-u",
        "--update",
        type="string",
        dest="update",
        metavar="UPDATEFILE",
        help="update terminology in UPDATEFILE",
    )

    parser.add_option(
        "-S",
        "--stopword-list",
        type="string",
        metavar="STOPFILE",
        dest="stopfile",
        help="read stopword (term exclusion) list from STOPFILE (default {})".format(
            file_discovery.get_abs_data_filename("stoplist-en")
        ),
    )

    parser.set_defaults(foldtitle=True, ignorecase=False)
    parser.add_option(
        "-F",
        "--fold-titlecase",
        callback=fold_case_option,
        action="callback",
        help='fold "Title Case" to lowercase (default)',
    )
    parser.add_option(
        "-C",
        "--preserve-case",
        callback=preserve_case_option,
        action="callback",
        help="preserve all uppercase/lowercase",
    )
    parser.add_option(
        "-I",
        "--ignore-case",
        dest="ignorecase",
        action="store_true",
        help="make all terms lowercase",
    )

    parser.add_option(
        "",
        "--accelerator",
        dest="accelchars",
        default="",
        metavar="ACCELERATORS",
        help="ignore the given accelerator characters when matching",
    )

    parser.add_option(
        "-t",
        "--term-words",
        type="int",
        dest="termlength",
        default="3",
        help="generate terms of up to LENGTH words (default 3)",
        metavar="LENGTH",
    )
    parser.add_option(
        "",
        "--nonstop-needed",
        type="int",
        dest="nonstopmin",
        default="1",
        help="omit terms with less than MIN nonstop words (default 1)",
        metavar="MIN",
    )
    parser.add_option(
        "",
        "--inputs-needed",
        type="int",
        dest="inputmin",
        help="omit terms appearing in less than MIN input files (default 2, or 1 if only one input file)",
        metavar="MIN",
    )
    parser.add_option(
        "",
        "--fullmsg-needed",
        type="int",
        dest="fullmsgmin",
        default="1",
        help="omit full message terms appearing in less than MIN different messages (default 1)",
        metavar="MIN",
    )
    parser.add_option(
        "",
        "--substr-needed",
        type="int",
        dest="substrmin",
        default="2",
        help="omit substring-only terms appearing in less than MIN different messages (default 2)",
        metavar="MIN",
    )
    parser.add_option(
        "",
        "--locs-needed",
        type="int",
        dest="locmin",
        default="2",
        help="omit terms appearing in less than MIN different original source files (default 2)",
        metavar="MIN",
    )

    parser.add_option(
        "",
        "--sort",
        dest="sortorders",
        action="append",
        type="choice",
        choices=TerminologyExtractor.sortorders_default,
        metavar="ORDER",
        help="output sort order(s): {} (may repeat option, default is all in above order)".format(
            ", ".join(TerminologyExtractor.sortorders_default)
        ),
    )

    parser.add_option(
        "",
        "--source-language",
        dest="sourcelanguage",
        default="en",
        help="the source language code (default 'en')",
        metavar="LANG",
    )
    parser.add_option(
        "-v",
        "--invert",
        dest="invert",
        action="store_true",
        default=False,
        help="invert the source and target languages for terminology",
    )
    parser.set_usage()
    parser.description = __doc__
    parser.run()


if __name__ == "__main__":
    main()
