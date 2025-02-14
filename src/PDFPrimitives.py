import os, io
import re
from typing import Any, Tuple, NewType, List, Union
import zlib
from src.utils import *
from PIL.Image import Image, open as open_image

LaxTuple = NewType("LaxTuple", Tuple["PDFPrimitive", bytes])


class PDFElement:
    def __init__(self) -> None: ...
    @staticmethod
    def parse(data: bytes):
        return PDFElement()

    def __repr__(self) -> str:
        return "PDFElement()"


############## pdf primitives ##############
class PDFName(PDFElement):
    def __init__(self, value: bytes) -> None:
        self.__value = value

    @property
    def value(self):
        return self.__value

    @staticmethod
    def parse(data: bytes):
        if not PDFName.is_name(data):
            raise ValueError("not a name")
        return PDFName(data[1:].decode())

    @staticmethod
    def is_name(data: bytes):
        return data.startswith(b"/") and data.find(b" ") == -1

    def try_lax(data: bytes):
        if not PDFName.is_name(data):
            return None
        else:
            return PDFName(data[1:].decode())

    def __repr__(self) -> str:
        return f"PDFName(/{self.__value})"

    def __eq__(self, value: Any) -> bool:
        if isinstance(value, PDFName):
            return self.__value == value.value
        if isinstance(value, str):
            return self.__value == value
        return super().__eq__(value)

    def __str__(self) -> str:
        return f"/{self.value}"

    def __hash__(self) -> int:
        return hash(str(self))


class PDFIndirectReference(PDFElement):
    pattern = rb"(?P<ON>\d{1,})\s(?P<GN>\d{1,})\sR"

    def __init__(self, on: int, gn: int) -> None:
        self.on: int = on
        self.gn: int = gn

    def get(self, file: "PDFFile") -> "PDFObject":
        return file.get_object(self.on)

    def __call__(self, file: "PDFFile") -> "PDFObject":
        return self.get(file)

    @staticmethod
    def lax(data: bytes) -> bool:
        r = re.search(b"^" + PDFIndirectReference.pattern, data)
        if r:
            on = int(r.group("ON"))
            gn = int(r.group("GN"))

            return PDFIndirectReference(on, gn), data[r.end() :]
        return None, data

    def __repr__(self) -> str:
        return f"PDFIndirectReference({self.on},{self.gn})"


class PDFDict(dict):
    def __setitem__(self, key: PDFName, value: Any) -> None:
        if isinstance(key, str):
            return super().__setitem__(PDFName(key), value)
        elif isinstance(key, PDFName):
            return super().__setitem__(key, value)
        else:
            raise ValueError("key Must be a PDFname or str object")

    def __getitem__(self, key: PDFName) -> None:
        if isinstance(key, str):
            return super().__getitem__(PDFName(key))
        elif isinstance(key, PDFName):
            return super().__getitem__(key)
        else:
            raise ValueError("key Must be a PDFname or str object")

    def get(self, key: PDFName, default: Any = None) -> Any:
        try:
            if isinstance(key, str):
                return super().__getitem__(PDFName(key))
            elif isinstance(key, PDFName):
                return super().__getitem__(key)
        except KeyError:
            return default

    def __contains__(self, key: object) -> bool:
        if isinstance(key, str):
            return super().__contains__(PDFName(key))
        return super().__contains__(key)

    def __repr__(self) -> str:
        return f"pdfdict({super().__repr__()})"

    @staticmethod
    def lax(data: bytes) -> LaxTuple:
        if not data.startswith(b"<<"):
            raise ValueError("not a dict")
        data = data[2:].lstrip()
        res = PDFDict()
        while True:
            key, data = PDFObject.lax_next_elem(data)
            if key == b">>":
                break
            val, data = PDFObject.lax_next_elem(data)
            res[key] = val
            if data.find(b"\n") == -1:
                break
        data = data.lstrip()
        if data.startswith(b"stream"):
            return PDFStream.lax(res, data)
        return res, data


class PDFList(list):
    def __repr__(self) -> str:
        return f"pdflist({super().__repr__()})"

    @staticmethod
    def lax(data: bytes) -> LaxTuple:
        if not data.startswith(b"["):
            raise ValueError("not a list")
        data = data[1:].lstrip()
        res = PDFList()
        while True:
            val, data = PDFObject.lax_next_elem(data)
            if val == b"]":
                break
            res.append(val)
        return res, data

    def __contains__(self, value: Any) -> bool:
        return any([x for x in self if x == value])


class PDFStr(str):
    def __new__(cls, value):
        # Escape special characters
        value = value.replace("(", "\\(")
        value = value.replace(")", "\\)")
        # Add more replacements as needed...

        # Create the new object
        obj = str.__new__(cls, value)
        return obj

    @staticmethod
    def lax(data: bytes):
        ptrn = rb"^(?<!\\\\)\((?P<string>.*)(?<!\\\\)\)"
        if string := re.search(ptrn, data):
            data = data[string.end() :]
            string: str = string.group("string")
            if re.search(rb"(?<!\\)[\(\)\n\r\t\b\f]|(?<!\\)\\(?<!\\)", string):
                raise ValueError("Unencoded string")
            string = re.sub(
                rb"\\([\(\)\\\n\r\t\b\f])", lambda m: m.group(1), string
            ).decode()
            return PDFStr(string), data
        raise ValueError("Not a PDF string")

    @staticmethod
    def lax_hex(data: bytes):
        ptrn = rb"^\<(?P<hexstring>[0-9A-Fa-f]*)\>"
        string = re.search(ptrn, data)
        if string:
            data = data[string.end() :]
            string: str = string.group("hexstring").decode()
            string = bytes.fromhex(string)
            return string, data
        raise ValueError("Not a hex string")


class PDFFilter:
    def __init__(self, encode, decode) -> None:
        self.encode = encode
        self.decode = decode


class PDFStream(PDFElement):
    streamStartLen = len(b"stream\n")
    streamEndLen = len(b"endstream")
    filters_encoders = {
        "ASCIIHexDecode": PDFFilter(lambda b: b, lambda b: b),
        "ASCII85Decode": PDFFilter(lambda b: b, lambda b: b),
        "LZWDecode": PDFFilter(lambda b: b, lambda b: b),
        "FlateDecode": PDFFilter(zlib.compress, zlib.decompress),
        "RunLengthDecode": PDFFilter(lambda b: b, lambda b: b),
        "CCITTFaxDecode": PDFFilter(lambda b: b, lambda b: b),
        "JBIG2Decode": PDFFilter(lambda b: b, lambda b: b),
        "DCTDecode": PDFFilter(lambda b: b, lambda b: open_image(io.BytesIO(b))),
    }

    def __init__(self, streamDict: PDFDict, buffer: bytes) -> None:
        # self.__streamDict = streamDict
        self.buffer = buffer
        self.__length = streamDict.get("Length", 0)
        self.filters = streamDict.get(PDFName("Filter"), PDFList())
        self.filters = (
            self.filters
            if isinstance(self.filters, PDFList)
            else PDFList([self.filters])
        )
        self.DecodeParms = streamDict.get("DecodeParms")
        self.F = streamDict.get("F")
        self.FFilter = streamDict.get("FFilter")
        self.FDecodeParams = streamDict.get("FDecodeParams")
        self.Resources = PDFResources(streamDict.get("Resources", PDFDict()))
        self.Subtype = streamDict.get("Subtype")

    def __len__(self):
        return self.__length

    def apply_filters(self):
        for filter in self.filters:
            self.buffer = self.filters_encoders[filter.value].encode(self.buffer)

    def unapply_filters(self):
        for filter in self.filters:
            self.buffer = self.filters_encoders[filter.value].decode(self.buffer)

    @staticmethod
    def lax(streamDict: PDFDict, data: bytes) -> LaxTuple:
        length = streamDict["Length"]
        buffer = data[PDFStream.streamStartLen : PDFStream.streamStartLen + length]
        data = data[PDFStream.streamStartLen + length + 1 + PDFStream.streamEndLen :]
        return PDFStream(streamDict, buffer), data

    def __repr__(self) -> str:
        return f"PDFStream({self.__length})"


class PDFNull(PDFElement):
    def __repr__(self) -> str:
        return "PDFNull()"


class PDFObject(PDFElement):
    def __init__(self, on: int, gn: int, content: "PDFPrimitive") -> None:
        self.on = on
        self.gn = gn
        self.content: "PDFPrimitive" = content

    def __getattr__(self, name):
        if hasattr(self.content, name):
            return getattr(self.content, name)
        try:
            return self.content[name]
        except:
            raise AttributeError(name)

    def __repr__(self) -> str:
        return f"PDFObject({self.on},{self.gn},{self.content})"

    @staticmethod
    def read(file, start: int):
        # file = open("r")
        file.seek(start, os.SEEK_SET)
        buffer = b""
        line = file.readline()
        res = re.search(rb"^(?P<ON>\d{1,})\s(?P<GN>\d{1,})\sobj", line)
        on = int(res.group("ON"))
        gn = int(res.group("GN"))
        while not (line := file.readline()).startswith(b"endobj"):
            buffer += line
        return PDFObject(on, gn, PDFObject.lax(buffer))

    @staticmethod
    def lax(data: bytes) -> Any:
        content, data = PDFObject.lax_next_elem(data)
        if len(data.strip()) != 0:
            raise ValueError("problem parsing")
        return content

    @staticmethod
    def lax_next_elem(data: bytes):
        data = data.lstrip()
        space = getTokenIDX(data)
        space = len(data) if space < 0 else space
        token = data[:space]
        if (_ := token.find(b"]")) != -1:
            space = _
            token = data[:space]
        r = None
        if data.startswith(b"<<"):
            return PDFDict.lax(data)
        elif (r := PDFIndirectReference.lax(data))[0] != None:
            # before int!
            return r
        elif PDFName.is_name(token):
            return PDFName.parse(token), data[space:]
        elif is_int(token):
            return int(token), data[space:]
        elif is_float(token):
            return float(token), data[space:]
        elif data.startswith(b"["):
            return PDFList.lax(data)
        elif data.startswith(b"("):
            return PDFStr.lax(data)
        elif data.startswith(b"<"):
            return PDFStr.lax_hex(data)
        elif data.startswith(b">>"):
            return b">>", data[2:]
        elif data.startswith(b"]"):
            return b"]", data[1:]
        elif token == b"false":
            return False, data[space:]
        elif token == b"true":
            return True, data[space:]
        elif token == b"null":
            return PDFNull(), data[space:]
        else:
            print("bad!")
            idx = data.find(b"\n")
            return data[:idx], data[idx + 1 :]


class PDFComment(PDFElement):
    value: bytes

    def __init__(self, data: bytes) -> None:
        self.value = data
        super().__init__()

    @staticmethod
    def parse(data: bytes):
        # print(data[0:1],b"\x37")
        if data[:1] != b"%":
            raise ValueError("not a comment")
        return PDFComment(data[1:].replace(b"\n", b"").replace(b"\r", b""))


class Rectangle:
    def __init__(self, corners: PDFList[int, int, int, int]) -> None:
        if len(corners) != 4 or not all(isinstance(i, (int, float)) for i in corners):
            raise ValueError("not a rectangle")
        self.x, self.y, self.width, self.height = corners


class PDFHighObject:
    # schema:Schema = Schema()
    def __init__(self, obj: PDFObject) -> None:
        self._on = obj.on
        self._gn = obj.gn

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            + ", ".join([f"{n}={v}" for n, v in vars(self).items()])
            + ")"
        )


class PDFResources(PDFHighObject):
    def __init__(self, obj: PDFObject) -> None:
        self.ExtGState: None = obj.get("ExtGState")
        self.ColorSpace: None = obj.get("ColorSpace")
        self.Pattern: None = obj.get("Pattern")
        self.Shading: None = obj.get("Shading")
        self.XObject: PDFDict[PDFIndirectReference] = obj.get("XObject", PDFDict())
        self.Font: None = obj.get("Font")
        self.ProcSet: None = obj.get("ProcSet")
        self.Properties: None = obj.get("Properties")
        self.ExtResources: None = obj.get("ExtResources")


PDFPrimitive = NewType(
    "PDFPrimitive",
    Union[
        PDFDict,
        PDFList,
        PDFStr,
        int,
        float,
        bool,
        PDFName,
        PDFNull,
        PDFIndirectReference,
        PDFStream,
    ],
)
