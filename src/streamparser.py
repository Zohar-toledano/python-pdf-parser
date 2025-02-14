import re
from PDFPrimitives import *


class StreamParseEnd(Exception): ...


class StreamCommand:
    operator: str

    @classmethod
    def from_str(cls, data: str):
        return cls()

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            + ", ".join([f"{n}={v}" for n, v in vars(self).items() if not callable(v)])
            + ")"
        )


class StreamCommandFloats(StreamCommand):
    @classmethod
    def from_str(cls, data: str):
        return cls(*(float(i) for i in data.strip().split(b" ")))


class StreamCommandName(StreamCommand):
    def __init__(self, name: PDFName) -> None:
        self.name = name

    @classmethod
    def from_str(cls, data: str):
        return cls(PDFName.parse(data))


class StreamStack:
    __ptrn = re.compile(rb"((?<=(?:[\>\s\n\)\]]))|^)[A-Za-z\*]{1,3}(?:[\r\s\n])")
    operator = "q"
    end_operator = "Q"

    def __init__(self, stack):
        self.stack = stack

    def __repr__(self):
        return f"{self.__class__.__name__}({self.stack})"

    @staticmethod
    def lax(data: bytes):
        stack = []
        while data:
            try:
                st = None
                operator, operands, data2 = StreamStack.get_command(data)
                if operands.startswith(b"("):
                    st, data = PDFStr.lax(data.lstrip())
                    operator, operands, data = StreamStack.get_command(data)
                    operands = st
                else:
                    data = data2
                endScope, command, data = build_command(operator, operands, data)
                if endScope:
                    break
                stack.append(command)
            except StreamParseEnd:
                break
        return stack, data

    @staticmethod
    def get_stack(data: bytes):
        stack, data = StreamStack.lax(data)
        if data.strip() != b"":
            raise ValueError("problem parsing")
        return stack

    @staticmethod
    def get_command(data: bytes):
        _ = StreamStack.__ptrn.search(data)
        if _ == None:
            raise StreamParseEnd()
        operands = data[: _.start()].strip()
        operator = _.group().strip().decode()
        data = data[_.end() :]
        return operator, operands, data


#################### General graphics state ####################
class LineWidth(StreamCommand):
    operator = "w"

    def __init__(self, lw: float):
        self.lw = lw

    @staticmethod
    def from_str(data: str):
        return LineWidth(float(data))


class CurrentMatrix(StreamCommand):
    operator = "cm"

    def __init__(self, a: int, b: int, c: int, d: int, e: int, f: int):
        self.matrix = (a, b, c, d, e, f)

    @staticmethod
    def from_str(data: str):
        if isinstance(data, bytes):
            data = data.decode()
        return CurrentMatrix(*(float(i) for i in data.strip().split(" ")))


class LineCap(StreamCommand):
    operator = "J"

    def __init__(self, cap: int):
        self.cap = cap

    @staticmethod
    def from_str(data: str):
        return LineCap(int(data))


class LineJoin(StreamCommand):
    operator = "j"

    def __init__(self, join: int):
        self.join = join

    @staticmethod
    def from_str(data: str):
        return LineJoin(int(data))


class RenderingIntent(StreamCommandName):
    operator = "ri"


class Flatness(StreamCommand):
    operator = "i"

    def __init__(self, flatness: int):
        self.flatness = flatness

    @staticmethod
    def from_str(data: str):
        return Flatness(int(data))


class GraphicalState(StreamCommandName):
    operator = "gs"


#################### End General graphics state ###################
#################### Text-positioning operators ###############################
class Text(StreamCommand):
    operator = "BT"
    end_operator = "ET"

    def __init__(self, data: list):
        self.garbage = data

    @staticmethod
    def lax(data: bytes):
        s, data = StreamStack.lax(data)
        return Text(s), data


class TextMatrix(StreamCommand):
    operator = "Tm"

    def __init__(self, a: float, b: float, c: float, d: float, e: float, f: float):
        self.matrix = (a, b, c, d, e, f)

    @staticmethod
    def from_str(data: str):
        if isinstance(data, bytes):
            data = data.decode()
        return TextMatrix(*(float(i) for i in data.strip().split(" ")))


class TextDelta(StreamCommand):
    operator = "Td"

    def __init__(self, x: float, y: float):
        self.x, self.y = x, y

    @staticmethod
    def from_str(data: str):
        if isinstance(data, bytes):
            data = data.decode()
        x, y = data.strip().split(" ")
        return TextDelta(float(x), float(y))


class TextDelta2(TextDelta):
    operator = "TD"

    @staticmethod
    def from_str(data: str):
        _ = TextDelta.from_str(data)
        return TextDelta2(_.x, _.y)


class TextToStartOfLine(StreamCommand):
    operator = "T*"


class TextContent(StreamCommand):
    operator = "Tj"

    def __init__(self, data: PDFStr):
        self.data = data

    @staticmethod
    def from_str(data: str):
        return TextContent(PDFStr.lax(data)[0])


#################### End Text-positioning operators ###############################
#################### Text state operators ###############################
class CharSpace(StreamCommandFloats):
    operator = "Tc"

    def __init__(self, char_space: float):
        self.value = char_space


class WordSpace(StreamCommandFloats):
    operator = "Tw"

    def __init__(self, word_space: float):
        self.value = word_space


class HorizontalScaling(StreamCommandFloats):
    operator = "Tz"

    def __init__(self, horizontal_scaling: float):
        self.value = horizontal_scaling


class TextLeading(StreamCommandFloats):
    operator = "TL"

    def __init__(self, text_leading: float):
        self.value = text_leading


class TextRenderingMode(StreamCommand):
    operator = "Tr"

    def __init__(self, text_rendering_mode: int):
        self.value = text_rendering_mode

    @classmethod
    def from_str(cls, data: str):
        return cls(int(data.strip()))


class TextRise(StreamCommandFloats):
    operator = "Ts"

    def __init__(self, text_rise: float):
        self.value = text_rise


class TextFont(StreamCommand):
    operator = "Tf"

    def __init__(self, text_font: PDFName, size: int):
        self.text_font = text_font
        self.size = size

    @classmethod
    def from_str(cls, data: str):
        data = data.strip()
        _ = data.find(b" ")
        return cls(PDFName.parse(data[:_]), int(data[_:].strip()))


#################### End Text state operators ###############################

#################### Path construction operators ###################


class m(StreamCommandFloats):
    operator = "m"

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


class l(StreamCommandFloats):
    operator = "l"

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


class CubicBezier(StreamCommandFloats):
    operator = "c"

    def __init__(
        self, x1: float, y1: float, x2: float, y2: float, x3: float, y3: float
    ):
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.x3 = x3
        self.y3 = y3


class v(StreamCommandFloats):
    operator = "v"

    def __init__(self, x2: float, y2: float, x3: float, y3: float):
        self.x2 = x2
        self.y2 = y2
        self.x3 = x3
        self.y3 = y3


class y(StreamCommandFloats):
    operator = "y"

    def __init__(self, x1: float, y1: float, x3: float, y3: float):
        self.x1 = x1
        self.y1 = y1
        self.x3 = x3
        self.y3 = y3


class CloseSubpath(StreamCommand):
    operator = "h"

    def __init__(self):
        pass

    @staticmethod
    def from_str(data: str):
        return CloseSubpath()


class RectanglePath(StreamCommandFloats):
    operator = "re"

    def __init__(self, x: float, y: float, width: float, hight: float):
        self.x = x
        self.y = y
        self.width = width
        self.hight = hight


#################### End Path construction operators ###################
#################### Path-painting operators ###################
class StrokePath(StreamCommand):
    operator = "S"


class StrokeClosePath(StreamCommand):
    operator = "s"


class FillPath(StreamCommand):
    operator = "f"


class FillPath2(StreamCommand):
    operator = "F"


class FillEvenOddPath(StreamCommand):
    operator = "f*"


class FillAndStrokePath(StreamCommand):
    operator = "B"


class FillAndStrokeEvenOddPath(StreamCommand):
    operator = "B*"


class FillAndStrokeClosePath(StreamCommand):
    operator = "b"


class FillAndStrokeClosePathEvenOdd(StreamCommand):
    operator = "b*"


class EndPath(StreamCommand):
    operator = "n"


class ClippingPath(StreamCommand):
    operator = "W"


class ClippingPathOddEven(StreamCommand):
    operator = "W*"


class PaintXObject(StreamCommandName):
    operator = "Do"


#################### End Path-painting operators ###################
#################### Marked-content operators ###################


class BeginMarkedContent(StreamCommandName):
    operator = "BMC"


class EndMarkedContent(StreamCommand):
    operator = "EMC"


class BDC(StreamCommand):
    operator = "BDC"

    def __init__(self, tag: PDFName, props: Union[PDFName, PDFDict]) -> None:
        self.tag = tag
        self.props = props

    @staticmethod
    def from_str(data):
        data = data.strip()
        _ = data.find(b" ")
        last = data[_ + 1 :]
        if PDFName.is_name(last):
            return BDC(PDFName.parse(data[:_]), PDFName.parse(last))
        return BDC(PDFName.parse(data[:_]), PDFDict.lax(last)[0])


#################### End Marked-content operators ###################
#################### Color operators ###################
# class CurrentColorSpaceStroke(StreamCommandName):
#     operator = "CS"
class CurrentColorSpace(StreamCommandName):
    operator = "cs"


class SetColor(StreamCommandFloats):
    operator = "sc"

    def __init__(self, *args: List[float]) -> None:
        for idx, n in enumerate(args):
            setattr(self, f"n{idx+1}", n)


class scn(SetColor):
    operator = "scn"

    def __init__(self, name: PDFName = None, *args: List[float]) -> None:
        self.name = name
        super().__init__(*args)

    @classmethod
    def from_str(cls, data: str):
        _ = data.rfind(b"/")
        name = PDFName.parse(data[_:]) if PDFName.is_name(data[_:]) else None
        return cls(name, *(float(i) for i in data.strip().split(b" ")))


class SetGray(StreamCommandFloats):
    operator = "g"

    def __init__(self, gray_lvl: float):
        self.gray_lvl = gray_lvl


class SetRGBColor(StreamCommandFloats):
    operator = "rg"

    def __init__(self, r: float, g: float, b: float):
        self.r = r
        self.g = g
        self.b = b


class SetCYMKColor(StreamCommandFloats):
    operator = "k"

    def __init__(self, c: float, m: float, y: float, k: float):
        self.c = c
        self.m = m
        self.y = y
        self.k = k


class CurrentColorSpaceStroke(CurrentColorSpace):
    operator = "CS"


class SetColorStroke(SetColor):
    operator = "SC"


class SCN(scn):
    operator = "SCN"


class SetGrayStroke(SetGray):
    operator = "G"


class SetRGBColorStroke(SetRGBColor):
    operator = "RG"


class SetCMYKColorStroke(SetCYMKColor):
    operator = "K"


#################### End Color operators ###################


def build_command(operator: str, operands: bytes, data):

    command: str = None
    end_scope = False
    match operator:
        case "q":
            command, data = StreamStack.lax(data)
        case "Q" | Text.end_operator:
            end_scope = True
        case Text.operator:
            command, data = Text.lax(data)
        case LineWidth.operator:
            command = LineWidth.from_str(operands)
        case CurrentMatrix.operator:
            command = CurrentMatrix.from_str(operands)
        case LineCap.operator:
            command = LineCap.from_str(operands)
        case LineJoin.operator:
            command = LineJoin.from_str(operands)
        case RenderingIntent.operator:
            command = RenderingIntent.from_str(operands)
        case Flatness.operator:
            command = Flatness.from_str(operands)
        case GraphicalState.operator:
            command = GraphicalState.from_str(operands)
        case TextMatrix.operator:
            command = TextMatrix.from_str(operands)
        case TextDelta2.operator:
            command = TextDelta2.from_str(operands)
        case TextToStartOfLine.operator:
            command = TextToStartOfLine()
        case TextContent.operator:
            # already a PDFStr!!!
            command = TextContent(operands)
        case CubicBezier.operator:
            command = CubicBezier.from_str(operands)
        case v.operator:
            command = v.from_str(operands)
        case y.operator:
            command = y.from_str(operands)
        case CloseSubpath.operator:
            command = CloseSubpath.from_str(operands)
        case m.operator:
            command = m.from_str(operands)
        case l.operator:
            command = l.from_str(operands)
        case RectanglePath.operator:
            command = RectanglePath.from_str(operands)
        case StrokePath.operator:
            command = StrokePath()
        case StrokeClosePath.operator:
            command = StrokeClosePath()
        case FillPath.operator:
            command = FillPath()
        case FillPath2.operator:
            command = FillPath2()
        case FillEvenOddPath.operator:
            command = FillEvenOddPath()
        case FillAndStrokePath.operator:
            command = FillAndStrokePath()
        case FillAndStrokeEvenOddPath.operator:
            command = FillAndStrokeEvenOddPath()
        case FillAndStrokeClosePath.operator:
            command = FillAndStrokeClosePath()
        case FillAndStrokeClosePathEvenOdd.operator:
            command = FillAndStrokeClosePathEvenOdd()
        case EndPath.operator:
            command = EndPath()
        case ClippingPath.operator:
            command = ClippingPath()
        case ClippingPathOddEven.operator:
            command = ClippingPathOddEven()
        case PaintXObject.operator:
            command = PaintXObject.from_str(operands)
        case BeginMarkedContent.operator:
            command = BeginMarkedContent.from_str(operands)
        case BDC.operator:
            command = BDC.from_str(operands)
        case EndMarkedContent.operator:
            command = EndMarkedContent()
        case CurrentColorSpace.operator:
            command = CurrentColorSpace.from_str(operands)
        case SetColor.operator:
            command = SetColor.from_str(operands)
        case scn.operator:
            command = scn.from_str(operands)
        case SetGray.operator:
            command = SetGray.from_str(operands)
        case SetRGBColor.operator:
            command = SetRGBColor.from_str(operands)
        case SetCYMKColor.operator:
            command = SetCYMKColor.from_str(operands)
        case CurrentColorSpaceStroke.operator:
            command = CurrentColorSpaceStroke.from_str(operands)
        case SetColorStroke.operator:
            command = SetColorStroke.from_str(operands)
        case SCN.operator:
            command = SCN.from_str(operands)
        case SetGrayStroke.operator:
            command = SetGrayStroke.from_str(operands)
        case SetRGBColorStroke.operator:
            command = SetRGBColorStroke.from_str(operands)
        case SetCMYKColorStroke.operator:
            command = SetCMYKColorStroke.from_str(operands)
        case CharSpace.operator:
            command = CharSpace.from_str(operands)
        case WordSpace.operator:
            command = WordSpace.from_str(operands)
        case HorizontalScaling.operator:
            command = HorizontalScaling.from_str(operands)
        case TextLeading.operator:
            command = TextLeading.from_str(operands)
        case TextRenderingMode.operator:
            command = TextRenderingMode.from_str(operands)
        case TextRise.operator:
            command = TextRise.from_str(operands)
        case TextFont.operator:
            command = TextFont.from_str(operands)
        case _:
            print("unknown operator", operator)
            raise NotImplementedError()
            # raise ValueError("unknown operator {}".format(operator))
            command = operator, operands.decode()

    return end_scope, command, data


if __name__ == "__main__":
    import json

    with open("./stream.txt", "rb") as f:
        data = f.read()

    with open("tets.json", "w") as f:
        json.dump(StreamStack.get_stack(data), f, indent=4, default=repr)
