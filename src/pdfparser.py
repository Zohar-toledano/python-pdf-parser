import os
from typing import Any, Tuple, NewType, List, Union, Callable
import io
from PDFPrimitives import *
from streamparser import *


# https://web.archive.org/web/20141010035745/http://gnupdf.org/Introduction_to_PDF
TRAILER_STRING = b"trailer\n"


############## pdf file components ##############
class PDFTrailer:
    start_xref: int
    data_temp: bytes

    def __init__(self, start_xref, pdf_elem: PDFObject) -> None:
        self.start_xref = start_xref
        self.trailer_root: PDFRoot = PDFRoot(pdf_elem)

    @staticmethod
    def parse(data: bytes):
        # data = [i for i in data.split(b"\n") if len(i) >0]
        # print(data)
        # if PDFComment(data[-1]).value != b"%EOF":
        # 	raise ValueError("not a trailer")
        # start_xref = data[-2].decode
        data = data.strip()
        if not data.endswith(rb"%%EOF"):
            raise ValueError("not a trailer")
        start_xref_string = b"startxref"
        start_xref_loc = data.find(start_xref_string)
        _ = start_xref_loc + len(start_xref_string) + 1
        start_xref = int(data[_ : data.find(b"\n", _)].decode())
        trailerDict = PDFObject.lax(data[:start_xref_loc])
        return PDFTrailer(start_xref, trailerDict)

    @staticmethod
    def read(file):
        # def read(file:BufferedReader):
        data = bytearray()
        for i in read_reverse_order(file):
            if i == TRAILER_STRING:
                break
            i.extend(data)
            data = i
        return PDFTrailer.parse(data)

    def __repr__(self) -> str:
        return f"PDFTrailer({self.start_xref},{self.data_temp})"


class XREFTable:
    def __init__(
        self, count_start: int, count: int, entries: List["XREFEntry"]
    ) -> None:
        if len(entries) != count:
            raise ValueError(f"Expected {count} entries, got {len(entries)}")

        self.count_start = count_start
        self.count = count
        self.entries = entries

    def __getitem__(self, key: int) -> "XREFEntry":
        return self.entries[key - self.count]

    @staticmethod
    def read(file, start):
        file.seek(start, os.SEEK_SET)
        xref = file.readline()
        count_start, count = file.readline().split(b" ")
        entries = []
        for i in file.readlines():
            if i == TRAILER_STRING:
                break
            if len(i) == 20:
                entry = XREFEntry.parse(i)
                entries.append(entry)
            else:
                raise ValueError(f"Entry {i} is not 20 bytes long")
        return XREFTable(int(count_start), int(count), entries)


class XREFEntry(PDFElement):
    def __init__(
        self, offset: int, gen: int, free: bool, content: PDFObject = None
    ) -> None:
        if content is not None:
            self.content = content
        self.offset = offset
        self.gen = gen
        self.free = free

    @staticmethod
    def parse(data: bytes):
        offset, gen, state = data.strip().split(b" ")
        return XREFEntry(int(offset), int(gen), state == b"f")

    def __repr__(self) -> str:
        return f"XREFEntry({self.offset},{self.gen},{self.free})"


#############################


class PDFRoot(PDFHighObject):
    def __init__(self, obj: PDFObject) -> None:
        if not isinstance(obj, PDFDict):
            raise ValueError("not a catalog")
        self.__size = obj["Size"]
        self.catalog: PDFIndirectReference = obj["Root"]

    def __len__(self) -> int:
        return self.__size


class PDFCatalog(PDFHighObject):
    def __init__(self, obj: PDFObject) -> None:
        if not isinstance(obj.content, PDFDict):
            raise ValueError("not a catalog")
        super().__init__(obj)
        if obj.content["Type"] != "Catalog":
            raise ValueError("not a catalog")
        self.PageLabels: None
        self.Names: None
        self.Dates: None
        self.PageLayout: None
        self.PageMode: None
        self.Outlines: None
        self.Threads: None
        self.OpenAction: None
        self.Pages: PDFIndirectReference = obj.content.get("Pages")


class PDFPageCollection(PDFHighObject):

    def __init__(self, obj: PDFObject) -> None:
        if obj.content["Type"] != PDFName("Pages"):
            raise ValueError("not a pages")
        super().__init__(obj)
        self.__count: int = obj.content["Count"]
        self.MediaBox: PDFList = obj.content.get("MediaBox", PDFList())
        self.Kids: PDFList = obj.content["Kids"]

    def __len__(self) -> int:
        return self.__count

    def __getitem__(self, key: int) -> PDFIndirectReference:
        return self.Kids[key]


class PDFPage(PDFHighObject):
    def __init__(self, obj: PDFObject) -> None:
        if obj.content["Type"] != PDFName("Page"):
            raise ValueError("not a page")
        super().__init__(obj)

        c = obj.content.get("Contents", PDFList())
        if not isinstance(c, PDFList):
            c = PDFList([c])

        self.Parent: PDFIndirectReference = obj.content["Parent"]
        self.Contents: PDFList = c
        self.Resources: PDFResources = PDFResources(
            obj.content.get("Resources", PDFDict())
        )
        self.CropBox: None = obj.content.get("CropBox")
        self.Annots: None = obj.content.get("Annots")
        self.MediaBox: None = obj.content.get("MediaBox")
        self.ID: None = obj.content.get("ID")


class PDFFont(PDFHighObject):
    def __init__(self, obj: PDFObject) -> None:
        self.Subtype: None = obj.get("Subtype")
        self.Name: PDFName = obj.get("Name")
        self.BaseFont: None = obj.get("BaseFont")
        self.FirstChar: None = obj.get("FirstChar")
        self.LastChar: None = obj.get("LastChar")
        self.Widths: PDFList = obj.get("Widths")
        self.FontDescriptor: PDFIndirectReference = obj.get("FontDescriptor")
        self.Encoding: None = obj.get("Encoding")
        self.ToUnicode: None = obj.get("ToUnicode")


class PDFFontDescriptor(PDFHighObject):
    def __init__(self, obj: PDFObject) -> None:
        if obj.get("Type") != "FontDescriptor":
            raise ValueError("not a font descriptor")

        self.FontName: None = obj.get("FontName")
        self.Flags: None = obj.get("Flags")
        self.FontBBox: None = obj.get("FontBBox")
        self.ItalicAngle: None = obj.get("ItalicAngle")
        self.Ascent: None = obj.get("Ascent")
        self.Descent: None = obj.get("Descent")
        self.Leading: None = obj.get("Leading")
        self.CapHeight: None = obj.get("CapHeight")
        self.XHeight: None = obj.get("XHeight")
        self.StemV: None = obj.get("StemV")
        self.StemH: None = obj.get("StemH")
        self.AvgWidth: None = obj.get("AvgWidth")
        self.MaxWidth: None = obj.get("MaxWidth")
        self.MissingWidth: None = obj.get("MissingWidth")
        self.FontFile: None = obj.get("FontFile")
        self.FontFile2: None = obj.get("FontFile2")
        self.FontFile3: None = obj.get("FontFile3")
        self.CharSet: None = obj.get("CharSet")


class PDFFile:

    def __init__(self, filename: str) -> None:
        self.__objects_cache = {}
        if isinstance(filename, str):
            self.__file = open(filename, "rb")
            data = PDFComment.parse(self.__file.read(0x9))
            data = data.value.decode()
            if not data.startswith("PDF-"):
                raise ValueError("Not a PDF file")
            self.version = data[4:]
            self.trailer = PDFTrailer.read(self.__file)
            self.xref_table = XREFTable.read(self.__file, self.trailer.start_xref)
            self.catalog = PDFCatalog(
                self.get_object(self.trailer.trailer_root.catalog.on)
            )
            self.pages = PDFPageCollection(self.get_object(self.catalog.Pages.on))
        elif filename is None:
            self.version = "1.4"
            self.trailer = PDFTrailer()

    def get_object(self, on: int) -> PDFObject:
        entry = self.xref_table[on]
        if hasattr(entry, "content"):
            print("cached")
            return entry.content
        obj = PDFObject.read(self.__file, entry.offset)
        setattr(entry, "content", obj)
        return obj

    def close(self) -> None:
        self.__file.close()

    def __len__(self) -> int:
        return len(self.pages)

    def __getitem__(self, key: int) -> PDFPage:
        return PDFPage(self.get_object(self.pages[key].on))


if __name__ == "__main__":
    ...

    f = PDFFile("ox_super.pdf")
    # # f = PDFFile("./Hello-stream.pdf")
    page: PDFPage = f[1]
    print(page.Resources)
    xo = page.Resources.XObject["Xi1"](f)
    _ = page.Contents[0](f)
    _.unapply_filters()
    xo.unapply_filters()
    print(StreamStack.get_stack(xo.buffer))
    print(StreamStack.get_stack(_.buffer))

    # print(zlib.decompress(xo.Resources.XObject["Im1"](f).buffer))
    # # for n,i in xo.Resources.XObject.items():
    # #     i = i(f)
    # #     i.unapply_filters()
    # #     if i.Subtype == "Image":
    # #         i.buffer.show()
    # #     else: print(i.buffer)
    # # o = f.get_object(8)
    # # o.unapply_filters()
    # # o.buffer.show()
    # # xo.unapply_filters()
    # # print(xo.buffer)
    # # for contentItem in page.Contents:
    # #     print("#################")
    # #     o = contentItem(f)
    # #     o.unapply_filters()

    # f.close()
