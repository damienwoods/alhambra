"""
A module for handling mixes.
"""

from __future__ import annotations
from abc import ABC, abstractmethod

import logging
from typing import (
    Any,
    Iterable,
    Literal,
    Optional,
    Sequence,
    TypeVar,
    Union,
    overload,
)

import numpy as np
import pandas as pd
import pint
import pint_pandas
from pint.quantity import Quantity
from tabulate import tabulate

from alhambra.seeds import Seed

from .tiles import TileList
from .tilesets import TileSet

import attrs

__all__ = (
    "uL",
    "uM",
    "nM",
    "Q_",
    "Component",
    "Strand",
    "FixedVolume",
    "FixedConcentration",
    "MultiFixedVolume",
    "MultiFixedConcentration",
    "Mix",
    "load_reference"
)

log = logging.getLogger("alhambra")

UR = pint.UnitRegistry()
pint_pandas.PintType.ureg = UR
UR.default_format = "~"

MOLARITY_TOLERANCE = UR.Quantity(1.0, "fM")
VOLUME_TOLERANCE = UR.Quantity(1.0, "pl")


uL = UR("uL")
uM = UR("uM")
nM = UR("nM")
Q_ = UR.Quantity

ROW_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWX"

MIXHEAD_EA = (
    "Comp",
    "Src []",
    "Dest []",
    "#",
    "Ea Tx Vol",
    "Tot Tx Vol",
    "Loc",
    "Note",
)
MIXHEAD_NO_EA = ("Comp", "Src []", "Dest []", "Tx Vol", "Loc", "Note")


@attrs.define(init=False, frozen=True, order=True, hash=True)
class WellPos:
    """A well position reference, allowing movement in various directions and bounds checking.

    This uses 1-indexed row and col, in order to match usual practice.  It can take either
    a standard well reference as a string, or two integers for the row and column.
    """

    row: int = attrs.field()
    col: int = attrs.field()
    platesize: Literal[96, 384] = 96

    @row.validator
    def _validate_row(self, v: int):
        rmax = 8 if self.platesize == 96 else 16
        if (v <= 0) or (v > rmax):
            raise ValueError(
                f"Row {ROW_ALPHABET[v-1]} ({v}) out of bounds for plate size {self.platesize}"
            )

    @col.validator
    def _validate_col(self, v: int):
        cmax = 12 if self.platesize == 96 else 24
        if (v <= 0) or (v > cmax):
            raise ValueError(
                f"Column {v} out of bounds for plate size {self.platesize}"
            )

    @overload
    def __init__(
        self, ref_or_row: int, col: int, /, *, platesize: Literal[96, 384] = 96
    ) -> None:  # pragma: no cover
        ...

    @overload
    def __init__(
        self, ref_or_row: str, col: None = None, /, *, platesize: Literal[96, 384] = 96
    ) -> None:  # pragma: no cover
        ...

    def __init__(
        self,
        ref_or_row: str | int,
        col: int | None = None,
        /,
        *,
        platesize: Literal[96, 384] = 96,
    ) -> None:
        match (ref_or_row, col):
            case (str(x), None):
                row: int = ROW_ALPHABET.index(x[0]) + 1
                col = int(x[1:])
            case (WellPos() as x, None):
                row = x.row
                col = x.col
                platesize = x.platesize
            case (int(x), int(y)):
                row = x
                col = y
            case _:
                raise TypeError

        if platesize not in (96, 384):
            raise ValueError(f"Plate size {platesize} not supported.")
        object.__setattr__(self, "platesize", platesize)

        self._validate_col(col)
        self._validate_row(row)

        object.__setattr__(self, "row", row)
        object.__setattr__(self, "col", col)

    def __str__(self) -> str:
        return f"{ROW_ALPHABET[self.row-1]}{self.col}"

    def __repr__(self) -> str:
        return f'WellPos("{self}")'

    def __eq__(self, other: Any) -> bool:
        match other:
            case WellPos(row, col, platesize):
                return (row == self.row) and (col == self.col)
            case str(ws):
                return self == WellPos(other, platesize=self.platesize)
            case _:
                return False

    def key_byrow(self) -> tuple[int, int]:
        "Get a tuple (row, col) key that can be used for ordering by row."
        return (self.row, self.col)

    def key_bycol(self) -> tuple[int, int]:
        "Get a tuple (col, row) key that can be used for ordering by column."
        return (self.col, self.row)

    def next_byrow(self) -> WellPos:
        "Get the next well, moving right along rows, then down."
        CMAX = 12 if self.platesize == 96 else 24
        return WellPos(
            self.row + (self.col + 1) // (CMAX + 1),
            (self.col) % CMAX + 1,
            platesize=self.platesize,
        )

    def next_bycol(self) -> WellPos:
        "Get the next well, moving down along columns, and then to the right."
        RMAX = 8 if self.platesize == 96 else 16
        return WellPos(
            (self.row) % RMAX + 1,
            self.col + (self.row + 1) // (RMAX + 1),
            platesize=self.platesize,
        )


@attrs.define(eq=True)
class _MixLine:
    """Class for handling a line of a (processed) mix recipe."""

    name: str | None
    source_conc: Quantity[float] | None
    dest_conc: Quantity[float] | None
    total_tx_vol: Quantity[float] | None
    number: int = 1
    each_tx_vol: Quantity[float] | None = None
    location: str | None = None
    note: str | None = None

    def toline(self, incea: bool):
        if incea:
            return [
                _formatter(getattr(self, x), x)
                for x in [
                    "name",
                    "source_conc",
                    "dest_conc",
                    "number",
                    "each_tx_vol",
                    "total_tx_vol",
                    "location",
                    "note",
                ]
            ]
        else:
            return [
                _formatter(getattr(self, x))
                for x in [
                    "name",
                    "source_conc",
                    "dest_conc",
                    "total_tx_vol",
                    "location",
                    "note",
                ]
            ]


def _formatter(x: int | float | str | None, t: str = "") -> str:
    match x:
        case y if isinstance(y, (int, str)):
            if t == "number" and x == 1:
                return ""
            return str(y)
        case None:
            return ""
        case y if isinstance(y, (float, Quantity)):
            return f"{y:.2f}"
        case _:
            raise TypeError


T = TypeVar("T")


class AbstractComponent(ABC):
    """Abstract class for a component in a mix."""

    @property
    @abstractmethod
    def name(self) -> str:  # pragma: no cover
        "Name of the component."
        ...

    @property
    @abstractmethod
    def concentration(self) -> Quantity[float]:  # pragma: no cover
        "(Source) concentration of the component as a pint Quantity."
        ...

    @abstractmethod
    def all_components(self) -> pd.DataFrame:  # pragma: no cover
        ...

    @abstractmethod
    def with_reference(self: T, reference: pd.DataFrame) -> T:  # pragma: no cover
        ...


@attrs.define()
class Component(AbstractComponent):
    """A single named component, potentially with a concentration."""

    name: str
    concentration: Quantity[float] | None = None

    def __eq__(self, other: Any) -> bool:
        if not other.__class__ == Component:
            return False
        if self.name != other.name:
            return False
        match (self.concentration, other.concentration):
            case (Quantity() as x, Quantity() as y):
                return abs(x - y) <= MOLARITY_TOLERANCE
            case x, y:
                return x == y

    def all_components(self) -> pd.DataFrame:
        df = pd.DataFrame(
            {
                "concentration_nM": [self.concentration.to("nM").magnitude],
                "component": [self],
            },
            index=pd.Index([self.name], name="name"),
        )
        return df

    def with_reference(self: Component, reference: pd.DataFrame) -> Component:
        if reference.index.name == "Name":
            ref_by_name = reference
        else:
            ref_by_name = reference.set_index("Name")
        ref_comp = ref_by_name.loc[self.name]

        ref_conc = UR.Quantity(ref_comp["Concentration (nM)"], "nM")

        if self.concentration is not None and (ref_conc != self.concentration):
            raise ValueError

        return Component(self.name, ref_conc)


@attrs.define()
class Strand(Component):
    """A single named strand, potentially with a concentration and sequence."""

    sequence: str | None = None

    def with_reference(self: Strand, reference: pd.DataFrame) -> Strand:
        if reference.index.name == "Name":
            ref_by_name = reference
        else:
            ref_by_name = reference.set_index("Name")
        ref_comp = ref_by_name.loc[self.name]

        ref_conc = UR.Quantity(ref_comp["Concentration (nM)"], "nM")

        if self.concentration is not None and (ref_conc != self.concentration):
            raise ValueError

        match (self.sequence, ref_comp["Sequence"]):
            case (None, None):
                seq = None
            case (str(x), None) | (str(x), "") | (None, str(x)):
                seq = x
            case (str(x), str(y)):
                if x != y:
                    raise ValueError
                seq = x

        return Strand(
            self.name,
            ref_conc,
            sequence=x,
        )


class AbstractAction(ABC):
    """
    Abstract class defining an action in a mix recipe.
    """

    @property
    def name(self) -> str:  # pragma: no cover
        ...

    @abstractmethod
    def tx_volume(
        self, mix_vol: Optional[Quantity[float]]
    ) -> Quantity[float]:  # pragma: no cover
        ...

    @abstractmethod
    def _mixlines(
        self, mix_vol: Quantity[float], locations: pd.DataFrame | None = None
    ) -> Sequence[_MixLine]:  # pragma: no cover
        ...

    @abstractmethod
    def all_components(
        self, mix_vol: Quantity[float]
    ) -> pd.DataFrame:  # pragma: no cover
        ...

    @abstractmethod
    def with_reference(self: T, reference: pd.DataFrame) -> T:  # pragma: no cover
        ...


def findloc(locations: pd.DataFrame | None, name: str) -> str | None:
    match findloc_tuples(locations, name):
        case (name, plate, well):
            if well:
                return f"{plate}: {well}"
            else:
                return f"{plate}"
        case None:
            return None


def findloc_tuples(
    locations: pd.DataFrame | None, name: str
) -> tuple[str, str, str] | None:
    if locations is None:
        return None
    locs = locations.loc[locations["Name"] == name]

    if len(locs) > 1:
        log.warning(f"Found multiple locations for {name}, using first.")
    elif len(locs) == 0:
        return None

    loc = locs.iloc[0]

    try:
        well = WellPos(loc["Well Position"])
    except Exception:
        well = loc["Well Position"]

    return (loc["Name"], loc["Plate"], well)


@attrs.define()
class FixedConcentration(AbstractAction):
    """A mix action adding one component at a fixed destination concentration."""

    component: AbstractComponent
    fixed_concentration: Quantity[float]

    def dest_concentration(self, mix_vol: Optional[Quantity[float]]) -> Quantity[float]:
        return self.fixed_concentration

    def tx_volume(self, mix_vol: Optional[Quantity[float]]) -> Quantity[float]:
        if mix_vol is None:
            raise ValueError
        retval: Quantity[float] = (
            mix_vol * self.fixed_concentration / self.component.concentration
        ).to_compact()
        retval.check("M")
        return retval

    def all_components(self, mix_vol: Quantity[float]) -> pd.DataFrame:
        comps = self.component.all_components()
        comps.concentration_nM *= (
            (self.fixed_concentration / self.component.concentration).to("").magnitude
        )
        return comps

    def _mixlines(
        self, mix_vol: Quantity[float], locations: pd.DataFrame | None = None
    ) -> Sequence[_MixLine]:

        return [
            _MixLine(
                name=self.component.name,
                source_conc=self.component.concentration,
                dest_conc=self.dest_concentration(mix_vol),
                total_tx_vol=self.tx_volume(mix_vol),
                location=findloc(locations, self.component.name),
            )
        ]

    def with_reference(self, reference: pd.DataFrame) -> FixedConcentration:
        return FixedConcentration(
            self.component.with_reference(reference), self.fixed_concentration
        )

    @property
    def name(self) -> str:
        return self.component.name


@attrs.define()
class FixedVolume(AbstractAction):
    """A mix action adding one component, at a fixed destination volume."""

    component: AbstractComponent
    fixed_volume: Quantity[float]

    def dest_concentration(self, mix_vol: Optional[Quantity[float]]) -> Quantity[float]:
        return (self.component.concentration * self.fixed_volume / mix_vol).to_compact()

    def tx_volume(self, mix_vol: Optional[Quantity[float]]) -> Quantity[float]:
        return self.fixed_volume

    def all_components(self, mix_vol: Quantity[float]) -> pd.DataFrame:
        comps = self.component.all_components()
        comps.concentration_nM *= (
            (self.dest_concentration(mix_vol) / self.component.concentration)
            .to("")
            .magnitude
        )
        return comps

    def _mixlines(
        self, mix_vol: Quantity[float], locations: pd.DataFrame | None = None
    ) -> Sequence[_MixLine]:

        return [
            _MixLine(
                name=self.component.name,
                source_conc=self.component.concentration,
                dest_conc=self.dest_concentration(mix_vol),
                total_tx_vol=self.tx_volume(mix_vol),
                location=findloc(locations, self.component.name),
            )
        ]

    def with_reference(self, reference: pd.DataFrame) -> FixedVolume:
        return FixedVolume(self.component.with_reference(reference), self.fixed_volume)

    @property
    def name(self) -> str:
        return self.component.name


def mixgaps(wl: Iterable[WellPos], by: Literal["row", "col"]) -> int:
    score = 0

    wli = iter(wl)

    getnextpos = WellPos.next_bycol if by == "col" else WellPos.next_byrow
    prevpos = next(wli)

    for pos in wli:
        if not (getnextpos(prevpos) == pos):
            score += 1
        prevpos = pos
    return score


def _empty_components() -> pd.DataFrame:
    cps = pd.DataFrame(
        index=pd.Index([], name="name"),
    )
    cps["concentration_nM"] = pd.Series([], dtype=float)
    cps["component"] = pd.Series([], dtype=object)
    return cps


@attrs.define()
class MultiFixedVolume(AbstractAction):
    """A action adding multiple components, each with the same destination volume."""

    components: Sequence[AbstractComponent]
    fixed_volume: Quantity[float]
    set_name: str | None = None
    compact_display: bool = True

    def with_reference(self, reference: pd.DataFrame) -> MultiFixedVolume:
        return MultiFixedVolume(
            [c.with_reference(reference) for c in self.components],
            self.fixed_volume,
            self.set_name,
            self.compact_display,
        )

    @property
    def source_concentration(self):
        conc = self.components[0].concentration

        if not all(c.concentration == conc for c in self.components):
            raise ValueError("Not all components have equal concentration.")

        return self.components[0].concentration

    def all_components(self, mix_vol: Quantity[float]) -> pd.DataFrame:
        newdf = _empty_components()

        for comp in self.components:
            comps = comp.all_components()
            comps.concentration_nM *= (
                (self.dest_concentration(mix_vol) / self.source_concentration)
                .to("")
                .magnitude
            )

            newdf, _ = newdf.align(comps)

            # FIXME: add checks
            newdf.loc[comps.index, "concentration_nM"] = newdf.loc[
                comps.index, "concentration_nM"
            ].add(comps.concentration_nM, fill_value=0.0)
            newdf.loc[comps.index, "component"] = comps.component

        return newdf

    def dest_concentration(self, mix_vol: Optional[Quantity[float]]) -> Quantity[float]:
        return (self.source_concentration * self.fixed_volume / mix_vol).to_compact()

    def each_volume(self, mix_vol: Optional[Quantity[float]]) -> Quantity[float]:
        return self.fixed_volume

    def tx_volume(self, mix_vol: Optional[Quantity[float]]) -> Quantity[float]:
        return self.fixed_volume * self.number

    def _mixlines(
        self, mix_vol: Quantity[float], locations: pd.DataFrame | None = None
    ) -> Sequence[_MixLine]:
        if not self.compact_display:
            return [
                _MixLine(
                    comp.name,
                    comp.concentration,
                    self.dest_concentration(mix_vol),
                    self.each_volume(mix_vol),
                    location=findloc(locations, comp.name),
                )
                for comp in self.components
            ]
        else:

            name, locs = self._compactstrs(locations=locations)

            return [
                _MixLine(
                    name,
                    self.source_concentration,
                    self.dest_concentration(mix_vol),
                    self.tx_volume(mix_vol),
                    self.number,
                    self.each_volume(mix_vol),
                    location=locs,
                )
            ]

    @property
    def number(self) -> int:
        return len(self.components)

    @property
    def name(self) -> str:
        if self.set_name is None:
            return ", ".join(c.name for c in self.components)
        else:
            return self.set_name

    def _compactstrs(self, locations: pd.DataFrame | None) -> tuple[str, str | None]:
        if locations is None:
            return ", ".join(c.name for c in self.components), None
        else:
            locs = [findloc_tuples(locations, c.name) for c in self.components]
            names = [c.name for c in self.components]

            if all(x is None for x in locs):
                return ", ".join(names), None

            if any(x is None for x in locs):
                raise ValueError(
                    [name for name, loc in zip(names, locs) if loc is None]
                )

            locdf = pd.DataFrame(locs, columns=("Name", "Plate", "Well Position"))

            locdf.sort_values(by=["Plate", "Well Position"])

            ns, ls = [], []

            for p, ll in locdf.groupby("Plate"):
                names: list[str] = list(ll["Name"])
                wells: list[WellPos] = list(ll["Well Position"])

                byrow = mixgaps(sorted(wells, key=WellPos.key_byrow), by="row")
                bycol = mixgaps(sorted(wells, key=WellPos.key_bycol), by="col")

                sortkey = WellPos.key_bycol if bycol <= byrow else WellPos.key_byrow
                sortnext = WellPos.next_bycol if bycol <= byrow else WellPos.next_byrow

                nw = sorted(
                    [(name, well) for name, well in zip(names, wells, strict=True)],
                    key=(lambda nwitem: sortkey(nwitem[1])),
                )

                wellsf = []
                nwi = iter(nw)
                prevpos = next(nwi)[1]
                wellsf.append(f"**{prevpos}**")
                for _, w in nwi:
                    if sortnext(prevpos) != w:
                        wellsf.append(f"**{w}**")
                    else:
                        wellsf.append(f"{w}")
                    prevpos = w

                ns.append(", ".join(n for n, _ in nw))
                ls.append(p + ": " + ", ".join(wellsf))

            return "\n".join(ns), "\n".join(ls)


@attrs.define()
class MultiFixedConcentration(AbstractAction):
    """A action adding multiple components, each with the same destination concentration."""

    components: Sequence[AbstractComponent]
    fixed_concentration: Quantity[float]
    set_name: str | None = None
    compact_display: bool = True

    def with_reference(self, reference: pd.DataFrame) -> MultiFixedVolume:
        return MultiFixedVolume(
            [c.with_reference(reference) for c in self.components],
            self.fixed_concentration,
            self.set_name,
            self.compact_display,
        )

    def all_components(self, mix_vol: Quantity[float]) -> pd.DataFrame:
        newdf = _empty_components()

        for comp in self.components:
            comps = comp.all_components()
            comps.concentration_nM *= (
                (self.dest_concentration(mix_vol) / comp.concentration).to("").magnitude
            )

            newdf, _ = newdf.align(comps)

            # FIXME: add checks
            newdf.loc[comps.index, "concentration_nM"] = newdf.loc[
                comps.index, "concentration_nM"
            ].add(comps.concentration_nM, fill_value=0.0)
            newdf.loc[comps.index, "component"] = comps.component

        return newdf

    def dest_concentration(self, mix_vol: Optional[Quantity[float]]) -> Quantity[float]:
        return self.fixed_concentration

    def tx_volume(self, mix_vol: Optional[Quantity[float]]) -> Quantity[float]:
        sum(
            (
                (mix_vol * self.fixed_concentration / comp.concentration).to(uL)
                for comp in self.components
            ),
            Q_(0.0, uL),
        )

    def _mixlines(
        self, mix_vol: Quantity[float], locations: pd.DataFrame | None = None
    ) -> Sequence[_MixLine]:
        if not self.compact_display:
            return [
                _MixLine(
                    comp.name,
                    comp.concentration,
                    self.dest_concentration(mix_vol),
                    (
                        mix_vol * self.fixed_concentration / comp.concentration
                    ).to_compact(),
                    location=findloc(locations, comp.name),
                )
                for comp in self.components
            ]
        else:

            name, vol, locs = self._compactstrs(locations=locations)

            return [
                _MixLine(
                    name,
                    self.source_concentration,
                    self.dest_concentration(mix_vol),
                    self.tx_volume(mix_vol),
                    self.number,
                    vol,
                    location=locs,
                )
            ]

    @property
    def number(self) -> int:
        return len(self.components)

    @property
    def name(self) -> str:
        if self.set_name is None:
            return ", ".join(c.name for c in self.components)
        else:
            return self.set_name

    def _compactstrs(self, locations: pd.DataFrame | None) -> tuple[str, str | None]:
        if locations is None:
            return ", ".join(c.name for c in self.components), None
        else:
            locs = [findloc_tuples(locations, c.name) for c in self.components]
            names = [c.name for c in self.components]

            if all(x is None for x in locs):
                return ", ".join(names), None

            if any(x is None for x in locs):
                raise ValueError(
                    [name for name, loc in zip(names, locs) if loc is None]
                )

            locdf = pd.DataFrame(locs, columns=("Name", "Plate", "Well Position"))

            locdf.sort_values(by=["Plate", "Well Position"])

            ns, ls = [], []

            for p, ll in locdf.groupby("Plate"):
                names: list[str] = list(ll["Name"])
                wells: list[WellPos] = list(ll["Well Position"])

                byrow = mixgaps(sorted(wells, key=WellPos.key_byrow), by="row")
                bycol = mixgaps(sorted(wells, key=WellPos.key_bycol), by="col")

                sortkey = WellPos.key_bycol if bycol <= byrow else WellPos.key_byrow
                sortnext = WellPos.next_bycol if bycol <= byrow else WellPos.next_byrow

                nw = sorted(
                    [(name, well) for name, well in zip(names, wells, strict=True)],
                    key=(lambda nwitem: sortkey(nwitem[1])),
                )

                wellsf = []
                nwi = iter(nw)
                prevpos = next(nwi)[1]
                wellsf.append(f"**{prevpos}**")
                for _, w in nwi:
                    if sortnext(prevpos) != w:
                        wellsf.append(f"**{w}**")
                    else:
                        wellsf.append(f"{w}")
                    prevpos = w

                ns.append(", ".join(n for n, _ in nw))
                ls.append(p + ": " + ", ".join(wellsf))

            return "\n".join(ns), "\n".join(ls)


@attrs.define()
class FixedRatio(AbstractAction):
    """A mix action taking a component from some"""

    component: AbstractComponent
    source_value: float
    dest_value: float

    @property
    def name(self) -> str:
        return self.component.name

    def tx_volume(self, mix_vol: Optional[Quantity[float]]) -> Quantity[float]:
        return mix_vol * self.dest_value / self.source_value

    def all_components(self, mix_vol: Quantity[float]) -> pd.DataFrame:
        v = self.component.all_components()
        v.loc[:, "concentration_nM"] *= self.dest_value / self.source_value
        return v

    def _mixlines(
        self, mix_vol: Quantity[float], locations: pd.DataFrame | None = None
    ) -> Sequence[_MixLine]:
        return _MixLine(
            self.name,
            str(self.source_value) + "x",
            str(self.dest_value) + "x",
            self.tx_volume(mix_vol),
        )

    def with_reference(self: T, reference: pd.DataFrame) -> T:
        return FixedRatio(
            self.component.with_reference(reference), self.source_value, self.dest_value
        )


@attrs.define()
class Mix(AbstractComponent):
    """Class denoting a Mix, a collection of source components mixed to
    some volume or concentration.
    """

    name: str
    actions: Sequence[AbstractAction]
    fixed_total_volume: Optional[Quantity[float]] = None
    fixed_concentration: Union[str, Quantity[float], None] = None
    buffer_name: Optional[str] = None
    reference: pd.DataFrame | None = None

    def __attrs_post_init__(self) -> None:
        if self.reference is not None:
            self.actions = [
                action.with_reference(self.reference) for action in self.actions
            ]

    @property
    def concentration(self) -> Quantity[float]:
        """
        Effective concentration of the mix.  Calculated in order:

        1. If the mix has a fixed concentration, then that concentration.
        2. If `fixed_concentration` is a string, then the final concentration of
           the component with that name.
        3. If `fixed_concentration` is none, then the final concentration of the first
           mix component.
        """
        if isinstance(self.fixed_concentration, pint.Quantity):
            return self.fixed_concentration
        elif isinstance(self.fixed_concentration, str):
            ac = self.all_components()
            return UR.Quantity(
                ac.loc[self.fixed_concentration, "concentration_nM"], "nM"
            )
        elif self.fixed_concentration is None:
            return self.actions[0].dest_concentration(self.total_volume)
        else:
            raise NotImplemented

    @property
    def total_volume(self) -> Quantity[float]:
        """
        Total volume of the the mix.  If the mix has a fixed total volume, then that,
        otherwise, the sum of the transfer volumes of each component.
        """
        if self.fixed_total_volume is not None:
            return self.fixed_total_volume
        else:
            return sum([c.tx_volume(None) for c in self.actions], 0 * UR("µL"))

    @property
    def buffer_volume(self) -> Quantity[float]:
        """
        The volume of buffer to be added to the mix, in addition to the components.
        """
        mvol = sum(c.tx_volume(self.total_volume) for c in self.actions)
        return self.total_volume - mvol

    def mdtable(self):
        tv = self.total_volume

        _mixlines = []

        for action in self.actions:
            _mixlines += action._mixlines(tv, locations=self.reference)

        if self.fixed_total_volume is not None:
            _mixlines.append(_MixLine("Buffer", None, None, self.buffer_volume))

        include_numbers = any(ml.number != 1 for ml in _mixlines)

        return tabulate(
            [ml.toline(include_numbers) for ml in _mixlines],
            MIXHEAD_EA if include_numbers else MIXHEAD_NO_EA,
            "pipe",
        )

    def all_components(self) -> pd.DataFrame:
        """
        Return a Series of all component names, and their concentrations (as pint nM).
        """
        cps = _empty_components()

        for action in self.actions:
            mcomp = action.all_components(self.total_volume)
            cps, _ = cps.align(mcomp)
            cps.loc[:, "concentration_nM"].fillna(0.0, inplace=True)
            cps.loc[mcomp.index, "concentration_nM"] += mcomp.concentration_nM
            cps.loc[mcomp.index, "component"] = mcomp.component
        return cps

    def _repr_markdown_(self):
        return str(self)

    def __str__(self):
        return (
            f"Table: Mix: {self.name}, Conc: {self.concentration:.2f}, Total Vol: {self.total_volume:.2f}\n\n"
            + self.mdtable()
        )

    def to_tileset(
        self,
        tilesets_or_lists: TileSet | TileList | Iterable[TileSet | TileList],
        *,
        seed: bool | Seed = False,
        base_conc=100 * UR("nM"),
    ) -> TileSet:
        """
        Given some :any:`TileSet`\ s, or lists of :any:`Tile`\ s from which to
        take tiles, generate an TileSet from the mix.
        """
        newts = TileSet()

        if isinstance(tilesets_or_lists, (TileList, TileSet)):
            tilesets_or_lists = [tilesets_or_lists]

        for comp, conc in self.all_components().items():
            new_tile = None
            for tl_or_ts in tilesets_or_lists:
                try:
                    if isinstance(tl_or_ts, TileSet):
                        tile = tl_or_ts.tiles[comp]
                    else:
                        tile = tl_or_ts[comp]
                    new_tile = tile.copy()
                    new_tile.stoic = float(conc / base_conc)
                    newts.tiles.add(new_tile)
                    break
                except KeyError:
                    pass
            if new_tile is None:
                log.warn(f"Component {comp} not found in tile lists.")

        match seed:
            case True:
                firstts = next(iter(tilesets_or_lists))
                assert isinstance(firstts, TileSet)
                newts.seeds["default"] = firstts.seeds["default"]
            case False:
                pass
            case Seed as x:
                newts.seeds["default"] = x

        if len(newts.tiles) == 0:
            raise ValueError("No mix components match tiles.")

        return newts

    def with_reference(self: Mix, reference: pd.DataFrame) -> Mix:
        new = Mix(
            name=self.name,
            actions=[action.with_reference(reference) for action in self.actions],
            fixed_total_volume=self.fixed_total_volume,
            fixed_concentration=self.fixed_concentration,
            buffer_name=self.buffer_name,
        )
        new.reference = reference
        return new


def load_reference(filename_or_file):
    df = pd.read_csv(filename_or_file)

    return df.reindex(
        ["Name", "Plate", "Well Position", "Concentration (nM)", "Sequence"],
        axis="columns",
    )
