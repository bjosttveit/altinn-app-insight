from __future__ import annotations
from abc import ABC, abstractmethod
from enum import Enum
from typing import TypedDict, NotRequired, Sequence, Unpack
import re


class ID(str):
    def __new__(cls, text):
        if re.search(r"\s", text) is not None:
            raise Exception("Id cannot contain whitespace")
        return super(ID, cls).__new__(cls, f"@{text}")

class PredicateType(Enum):
    Eq = "#eq?"
    NotEq = "#not-eq?"
    AnyEq = "#any-eq?"
    AnyNotEq = "#any-not-eq?"


class Predicate[PT: PredicateType]:
    def __init__(self, pt: PT, left: str | ID, right: str | ID):
        self.pt = pt
        self.left = left if isinstance(left, ID) else f'"{left}"'
        self.right = right if isinstance(right, ID) else f'"{right}"'

    def __repr__(self):
        return f"({self.pt.value} {self.left} {self.right})"


class Eq(Predicate[PredicateType.Eq]):
    def __init__(self, left: str | ID, right: str | ID):
        super().__init__(PredicateType.Eq, left, right)


class NotEq(Predicate[PredicateType.NotEq]):
    def __init__(self, left: str | ID, right: str | ID):
        super().__init__(PredicateType.NotEq, left, right)


class AnyEq(Predicate[PredicateType.AnyEq]):
    def __init__(self, left: str | ID, right: str | ID):
        super().__init__(PredicateType.AnyEq, left, right)


class AnyNotEq(Predicate[PredicateType.AnyNotEq]):
    def __init__(self, left: str | ID, right: str | ID):
        super().__init__(PredicateType.AnyNotEq, left, right)


class NodeArgs(TypedDict):
    id: NotRequired[ID]
    predicate: NotRequired[Predicate | Sequence[Predicate]]


class Node(ABC):
    # if kwargs could be the Unpack of a generic type bound to NodeArgs it would not be necessary to override the __init__, but this is currently not supported: https://github.com/python/typing/issues/1399
    def __init__(self, **kwargs: Unpack[NodeArgs]):
        self.kwargs = kwargs

    def get_named(self, key: str) -> str:
        if key in self.kwargs:
            node = self.kwargs[key]
            return f"\n{key}: {node}"
        return ""

    def get(self, key: str) -> str:
        if key in self.kwargs:
            node = UnpackNodes(self.kwargs[key])
            return "\n" + str(node)
        return ""

    @abstractmethod
    def str(self) -> str: ...

    def __str__(self):
        out = self.str()
        if "id" in self.kwargs:
            id = self.kwargs["id"]
            out += " " + str(id)
        if "predicate" in self.kwargs:
            predicate = self.kwargs["predicate"]
            out += "\n" + str(UnpackNodes(predicate))
        return out

    def __repr__(self):
        return self.__str__()

class UnpackNodes[N: Node | Predicate]:
    def __init__(self, nodes: N | Sequence[N]):
        self.nodes = nodes if isinstance(nodes, Sequence) else [nodes]

    def __repr__(self):
        return "\n".join(map(lambda node: str(node), self.nodes))

class Identifier(Node):
    def str(self):
        return "(identifier)"

class BaseListArgs(NodeArgs):
    identifier: NotRequired[Identifier | Sequence[Identifier]]

class BaseList(Node):
    def __init__(self, **kwargs: Unpack[BaseListArgs]):
        self.kwargs = kwargs

    def str(self):
        identifiers = self.get("identifier")
        return f"(base_list {identifiers})"

class DeclarationListArgs(NodeArgs):
    nodes: NotRequired[Node | Sequence[Node]]

class DeclarationList(Node):
    def __init__(self, **kwargs: Unpack[DeclarationListArgs]):
        self.kwargs = kwargs

    def str(self):
        nodes = self.get("nodes")
        return f"(declaration_list {nodes})"

class ClassDeclarationArgs(NodeArgs):
    name: NotRequired[Identifier]
    base_list: NotRequired[BaseList]
    body: NotRequired[DeclarationList]

class ClassDeclaration(Node):
    def __init__(self, **kwargs: Unpack[ClassDeclarationArgs]):
        self.kwargs = kwargs

    def str(self):
        name = self.get_named("name")
        base_list = self.get("base_list")
        body = self.get("body")
        return f"(class_declaration {name} {base_list} {body})"
