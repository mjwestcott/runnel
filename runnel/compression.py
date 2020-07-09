import gzip

from runnel.interfaces import Compressor

try:
    import lz4.frame as lz4
except ImportError:
    lz4 = None


class Gzip(Compressor):
    def compress(self, value):
        return gzip.compress(value)

    def decompress(self, value):
        return gzip.decompress(value)


class LZ4(Compressor):
    def compress(self, value):
        return lz4.compress(value)

    def decompress(self, value):
        return lz4.decompress(value)
