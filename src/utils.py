import os
def read_reverse_order(read_obj):
    read_obj.seek(0, os.SEEK_END)
    pointer_location = read_obj.tell()
    buffer = bytearray()

    while pointer_location >= 0:
        read_obj.seek(pointer_location)
        pointer_location -= 1
        new_byte = read_obj.read(1)
        if new_byte == b"\n":
            yield buffer[::-1]
            buffer = bytearray(b"\n")
        else:
            buffer.extend(new_byte)

    if len(buffer) > 0:
        yield buffer[::-1]


def is_int(token: bytes) -> bool:
    return token.lstrip(b"-").isdigit()


def is_float(token: bytes) -> bool:
    if token.count(b".") == 1:
        return token.lstrip(b"-").replace(b".", b"").isdigit()
    return False


def getTokenIDX(data: bytes) -> int:
    for idx, i in enumerate(data):
        if bytes([i]) in [b" ", b"\n", b"\r"]:
            return idx
    return -1

