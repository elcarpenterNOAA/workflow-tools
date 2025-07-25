from __future__ import annotations

import math
from datetime import datetime
from functools import partial
from importlib import import_module
from typing import TYPE_CHECKING, Callable, Union

import yaml

from uwtools.exceptions import UWConfigError
from uwtools.logging import log
from uwtools.strings import FORMAT

if TYPE_CHECKING:
    from collections import OrderedDict

INCLUDE_TAG = "!include"
YAMLKey = Union[bool, float, int, str]

# Public functions


def depth(d: dict) -> int:
    """
    The depth of a dictionary.

    :param d: The dictionary whose depth to calculate.
    :return: The length of the longest path to a value in the dictionary.
    """
    return (max(map(depth, d.values()), default=0) + 1) if isinstance(d, dict) else 0


def format_to_config(fmt: str) -> type:
    """
    Maps a CLI format name to its corresponding Config class.

    :param fmt: The format name as known to the CLI.
    :return: The appropriate Config class.
    """
    lookup = {
        FORMAT.fieldtable: "FieldTableConfig",
        FORMAT.ini: "INIConfig",
        FORMAT.nml: "NMLConfig",
        FORMAT.sh: "SHConfig",
        FORMAT.yaml: "YAMLConfig",
    }
    if fmt not in lookup:
        raise log_and_error("Format '%s' should be one of: %s" % (fmt, ", ".join(lookup)))
    cfgclass: type = getattr(import_module(f"uwtools.config.formats.{fmt}"), lookup[fmt])
    return cfgclass


def from_od(d: OrderedDict | dict) -> dict:
    """
    Return a (nested) dict with content equivalent to the given (nested) OrderedDict.

    :param d: A (possibly nested) OrderedDict.
    """
    return {key: from_od(val) if isinstance(val, dict) else val for key, val in d.items()}


def log_and_error(msg: str) -> Exception:
    """
    Log an error message and return an exception for the caller to potentially raise.

    :param msg: The error message to log and to associate with raised exception.
    :return: An exception containing the same error message.
    """
    log.error(msg)
    return UWConfigError(msg)


def uw_yaml_loader() -> type[yaml.SafeLoader]:
    """
    A loader with basic UW constructors added.
    """
    loader = yaml.SafeLoader
    for tag_class in (UWYAMLConvert, UWYAMLGlob, UWYAMLRemove):
        for tag in tag_class.TAGS:
            loader.add_constructor(tag, tag_class)
    return loader


def dict_to_yaml_str(d: dict, sort: bool = False) -> str:
    """
    Return a uwtools-conventional YAML representation of the given dict.

    :param d: A dict object.
    :param sort: Sort dict/mapping keys?
    """
    return yaml.dump(d, default_flow_style=False, indent=2, sort_keys=sort, width=math.inf).strip()


class UWYAMLTag:
    """
    A base class for custom UW YAML tags.
    """

    def __init__(self, _: yaml.SafeLoader, node: yaml.nodes.Node) -> None:
        self.node = node
        self.tag: str = node.tag
        self.value: str = node.value

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, UWYAMLTag):
            return NotImplemented
        return self.tag == other.tag and self.value == other.value

    def __hash__(self):
        return hash(str(self))

    def __repr__(self) -> str:
        return ("%s %s" % (self.tag, self.value)).strip()

    @staticmethod
    def represent(
        _dumper: yaml.Dumper,
        data: UWYAMLTag,
    ) -> yaml.nodes.Node:
        """
        Serialize a scalar value as "!type value".

        Implements the interface required by pyyaml's add_representer() function. See the pyyaml
        documentation for details.
        """
        return data.node


class UWYAMLTaggedStr(UWYAMLTag):
    """
    Support for YAML tags that target str values.
    """

    def __init__(self, loader: yaml.SafeLoader, node: yaml.nodes.ScalarNode) -> None:
        super().__init__(loader, node)
        if not isinstance(self.value, str):
            hint = (
                "%s %s" % (node.tag, node.value)
                if node.start_mark is None
                else node.start_mark.buffer.replace("\n\x00", "")
            )
            msg = "Value tagged %s must be type 'str' (not '%s') in: %s" % (
                node.tag,
                node.value.__class__.__name__,
                hint,
            )
            raise UWConfigError(msg)


class UWYAMLConvert(UWYAMLTaggedStr):
    """
    Support for YAML tags that specify type conversions.
    """

    TAGS = ("!bool", "!datetime", "!dict", "!float", "!int", "!list")
    TaggedValT = Union[bool, datetime, dict, float, int, list]

    def __repr__(self) -> str:
        return "%s %s" % (self.tag, self.converted)

    def __str__(self) -> str:
        return str(self.converted)

    @property
    def converted(self) -> UWYAMLConvert.TaggedValT:
        """
        Return the original YAML value converted to the type specified by the tag.

        :raises: Appropriate exception if the value cannot be represented as the required type.
        """
        load_as = lambda t, v: t(yaml.safe_load(v))
        converters: list[Callable[..., UWYAMLConvert.TaggedValT]] = [
            partial(load_as, bool),
            datetime.fromisoformat,
            partial(load_as, dict),
            float,
            int,
            partial(load_as, list),
        ]
        return dict(zip(UWYAMLConvert.TAGS, converters))[self.tag](self.value)


class UWYAMLGlob(UWYAMLTaggedStr):
    """
    Support for a YAML tag that specifies a glob pattern.
    """

    TAGS = ("!glob",)


class UWYAMLRemove(UWYAMLTag):
    """
    Support for a YAML tag that removes a key/value pair.
    """

    TAGS = ("!remove",)
