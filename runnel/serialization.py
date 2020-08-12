import json
from dataclasses import dataclass

from runnel.interfaces import Compressor, Serializer

try:
    import orjson
except ImportError:
    orjson = None


@dataclass(frozen=True)
class JSONSerializer(Serializer):
    compressor: Compressor = None

    @staticmethod
    def _default(obj):
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        return obj

    def dumps(self, value):
        return json.dumps(
            obj=value,
            default=self._default,
            separators=(',', ':'),
        ).encode("utf-8")

    def loads(self, value):
        return json.loads(value)


@dataclass(frozen=True)
class FastJSONSerializer(Serializer):
    compressor: Compressor = None

    def dumps(self, value):
        return orjson.dumps(value)

    def loads(self, value):
        return orjson.loads(value)


if orjson:
    default: Serializer = FastJSONSerializer()
else:
    default = JSONSerializer()
