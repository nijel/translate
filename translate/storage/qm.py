#
# Copyright 2007-2010 Zuza Software Foundation
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
#

"""
Module for parsing Qt .qm files.

.. note::

    Based on documentation from Gettext's .qm implementation
    (see *write-qt.c*) and on observation of the output of lrelease.

.. note::

    Certain deprecated section tags are not implemented.  These will break
    and print out the missing tag.  They are easy to implement and should
    follow the structure in 03 (Translation).  We could find no examples
    that use these so we'd rather leave it unimplemented until we
    actually have test data.

.. note::

    Many .qm files are unable to be parsed as they do not have the source
    text.  We assume that since they use a hash table to lookup the
    data there is actually no need for the source text.  It seems however
    that in Qt4's lrelease all data is included in the resultant .qm file.

.. note::

    We can only parse, not create, a .qm file.  The main issue is that we
    need to implement the hashing algorithm (which seems to be identical to the
    Gettext hash algorithm).  Unlike Gettext it seems that the hash is
    required, but that has not been validated.

.. note::

    The code can parse files correctly.  But it could be cleaned up to be
    more readable, especially the part that breaks the file into sections.

http://qt.gitorious.org/+kde-developers/qt/kde-qt/blobs/master/tools/linguist/shared/qm.cpp
`Plural information <http://qt.gitorious.org/+kde-developers/qt/kde-qt/blobs/master/tools/linguist/shared/numerus.cpp>`_
`QLocale languages <http://docs.huihoo.com/qt/4.5/qlocale.html#Language-enum>`_
"""

import codecs
import logging
import struct

from translate.misc.multistring import multistring
from translate.storage import base

logger = logging.getLogger(__name__)

QM_MAGIC_NUMBER = (0x3CB86418, 0xCAEF9C95, 0xCD211CBF, 0x60A1BDDD)


def qmunpack(file_="messages.qm"):
    """Helper to unpack Qt .qm files into a Python string."""
    with open(file_, "rb") as fh:
        s = fh.read()
        return "\\x%02x" * len(s) % tuple(map(ord, s))


class qmunit(base.TranslationUnit):
    """A class representing a .qm translation message."""


class qmfile(base.TranslationStore):
    """A class representing a .qm file."""

    UnitClass = qmunit
    Name = "Qt .qm file"
    Mimetypes = ["application/x-qm"]
    Extensions = ["qm"]
    _binary = True

    def __init__(self, inputfile=None, **kwargs):
        super().__init__(**kwargs)
        self.filename = ""
        if inputfile is not None:
            self.parsestring(inputfile)

    def serialize(self, out):
        """Output a string representation of the .qm data file."""
        raise NotImplementedError("Writing of .qm files is not supported yet")

    def parse(self, input):
        """Parses the given file or file source string."""
        if hasattr(input, "name"):
            self.filename = input.name
        elif not getattr(self, "filename", ""):
            self.filename = ""
        if hasattr(input, "read"):
            qmsrc = input.read()
            input.close()
            input = qmsrc
        if len(input) < 16:
            raise ValueError("This is not a .qm file: file empty or too small")
        magic = struct.unpack(">4L", input[:16])
        if magic != QM_MAGIC_NUMBER:
            raise ValueError("This is not a .qm file: invalid magic number")
        startsection = 16
        sectionheader = 5

        def section_debug(name, section_type, startsection, length):
            print(  # noqa: T201
                "Section: %s (type: %#x, offset: %#x, length: %d)"
                % (name, section_type, startsection, length)
            )

        while startsection < len(input):
            section_type, length = struct.unpack(
                ">BL", input[startsection : startsection + sectionheader]
            )
            if section_type == 0x42:
                # section_debug("Hash", section_type, startsection, length)
                # hash_start = startsection + sectionheader
                # hash_data = struct.unpack(">%db" % length, input[startsection + sectionheader:startsection + sectionheader + length])
                pass
            elif section_type == 0x69:
                # section_debug("Messages", section_type, startsection, length)
                messages_start = startsection + sectionheader
                messages_data = struct.unpack(
                    ">%db" % length,
                    input[
                        startsection + sectionheader : startsection
                        + sectionheader
                        + length
                    ],
                )
            elif section_type == 0x2F:
                # section_debug("Contexts", section_type, startsection, length)
                # contexts_start = startsection + sectionheader
                # contexts_data = struct.unpack(">%db" % length, input[startsection + sectionheader:startsection + sectionheader + length])
                pass
            elif section_type == 0x88:
                # section_debug("NumerusRules", section_type, startsection, length)
                # numerusrules_start = startsection + sectionheader
                # numerusrules_data = struct.unpack(">%db" % length, input[startsection + sectionheader:startsection + sectionheader + length])
                pass
            else:
                section_debug("Unkown", section_type, startsection, length)
            startsection = startsection + sectionheader + length
        pos = messages_start
        source = target = None
        while pos < messages_start + len(messages_data):
            (subsection,) = struct.unpack(">B", input[pos : pos + 1])
            if subsection == 0x01:  # End
                pos += 1
                if source is not None and target is not None:
                    newunit = self.addsourceunit(source)
                    newunit.target = target
                    source = target = None
                else:
                    raise ValueError("Old .qm format with no source defined")
                continue
            pos += 1
            (length,) = struct.unpack(">l", input[pos : pos + 4])
            if subsection == 0x03:  # Translation
                if length != -1:
                    (raw,) = struct.unpack(
                        ">%ds" % length, input[pos + 4 : pos + 4 + length]
                    )
                    string, _templen = codecs.utf_16_be_decode(raw)
                    if target:
                        target.extra_strings.append(string)
                    else:
                        target = multistring(string)
                    pos = pos + 4 + length
                else:
                    target = ""
                    pos += 4
            elif subsection == 0x06:  # SourceText
                source = input[pos + 4 : pos + 4 + length].decode("iso-8859-1")
                pos = pos + 4 + length
            elif subsection == 0x07:  # Context
                # context = input[pos + 4:pos + 4 + length].decode('iso-8859-1')
                pos = pos + 4 + length
            elif subsection == 0x08:  # Disambiguating-comment
                # comment = input[pos + 4:pos + 4 + length]
                pos = pos + 4 + length
            elif subsection == 0x05:  # hash
                # hash = input[pos:pos + 4]
                pos += 4
            else:
                if subsection == 0x02:  # SourceText16
                    subsection_name = "SourceText16"
                elif subsection == 0x04:  # Context16
                    subsection_name = "Context16"
                else:
                    subsection_name = "Unknown"
                logger.warning("Unimplemented: 0x%x %s", subsection, subsection_name)
                return

    def savefile(self, storefile):
        raise NotImplementedError("Writing of .qm files is not supported yet")
