import pint
from dataclasses import dataclass
from typing import Mapping, Tuple, Union, Sequence, Optional
from abc import ABC, abstractmethod, abstractproperty
from tabulate import tabulate

UR = pint.UnitRegistry()

MIXHEAD_EA = ("Comp", "Src []", "Dest []", "#", "Ea Tx Vol", "Tot Tx Vol")
MIXHEAD_NO_EA = ("Comp", "Src []", "Dest []", "Tx Vol")


class MixComp(ABC):
    @abstractproperty
    def name(self) -> str:
        ...

    @abstractmethod
    def dest_conc(self, mix_vol: Optional[pint.Quantity]) -> pint.Quantity:
        ...

    @abstractmethod
    def tx_vol(self, mix_vol: Optional[pint.Quantity]) -> pint.Quantity:
        ...

    @abstractmethod
    def mixlines(
        self, mix_vol: pint.Quantity, include_ea: bool
    ) -> Sequence[Sequence[Union[str, pint.Quantity, int]]]:
        ...

    @abstractproperty
    def number(self) -> int:
        ...

    @abstractmethod
    def all_comps(self, mix_vol: pint.Quantity) -> Mapping[str, pint.Quantity]:
        ...


class BaseComponent(ABC):
    @abstractproperty
    def name(self) -> str:
        ...

    @abstractproperty
    def conc(self) -> pint.Quantity:
        ...

    @abstractmethod
    def all_comps(self) -> Mapping[str, pint.Quantity]:
        ...


@dataclass
class FixedConc(MixComp):
    comp: BaseComponent
    set_dest_conc: pint.Quantity

    def dest_conc(self, mix_vol: Optional[pint.Quantity]) -> pint.Quantity:
        return self.set_dest_conc

    def tx_vol(self, mix_vol: Optional[pint.Quantity]) -> pint.Quantity:
        return (mix_vol * (self.set_dest_conc / self.comp.conc)).to_compact()

    def all_comps(self, mix_vol: pint.Quantity) -> Mapping[str, pint.Quantity]:
        return {
            n: c * (self.set_dest_conc / self.comp.conc)
            for n, c in self.comp.all_comps().items()
        }

    def mixlines(
        self, mix_vol: pint.Quantity, include_ea: bool
    ) -> Sequence[Sequence[Union[str, pint.Quantity, int]]]:
        if include_ea:
            [
                self.comp.name,
                self.comp.conc,
                self.dest_conc(mix_vol),
                "",
                "",
                self.tx_vol(mix_vol),
            ]

        return [
            [
                self.comp.name,
                self.comp.conc,
                self.dest_conc(mix_vol),
                self.tx_vol(mix_vol),
            ]
        ]

    @property
    def number(self) -> int:
        return 1

    @property
    def name(self) -> str:
        return self.comp.name


@dataclass
class FixedVol(MixComp):
    comp: BaseComponent
    set_dest_vol: pint.Quantity

    def dest_conc(self, mix_vol: Optional[pint.Quantity]) -> pint.Quantity:
        return (self.comp.conc * self.set_dest_vol / mix_vol).to_compact()

    def tx_vol(self, mix_vol: Optional[pint.Quantity]) -> pint.Quantity:
        return self.set_dest_vol

    def all_comps(self, mix_vol: pint.Quantity) -> Mapping[str, pint.Quantity]:
        return {
            n: c * (self.dest_conc(mix_vol) / self.comp.conc)
            for n, c in self.comp.all_comps().items()
        }

    def mixlines(
        self, mix_vol: pint.Quantity, include_ea: bool
    ) -> Sequence[Sequence[Union[str, pint.Quantity, int]]]:
        if include_ea:
            return [
                [
                    self.comp.name,
                    self.comp.conc,
                    self.dest_conc(mix_vol),
                    "",
                    "",
                    self.tx_vol(mix_vol),
                ]
            ]

        return [
            [
                self.comp.name,
                self.comp.conc,
                self.dest_conc(mix_vol),
                self.tx_vol(mix_vol),
            ]
        ]

    @property
    def number(self) -> int:
        return 1

    @property
    def name(self) -> str:
        return self.comp.name


@dataclass
class NFixedVol(MixComp):
    comp: BaseComponent
    set_number: int
    set_dest_vol: pint.Quantity

    def dest_conc(self, mix_vol: Optional[pint.Quantity]) -> pint.Quantity:
        return (self.comp.conc * self.set_dest_vol / mix_vol).to_compact()

    def all_comps(self, mix_vol: pint.Quantity) -> Mapping[str, pint.Quantity]:
        return {
            n: c * (self.dest_conc(mix_vol) / self.comp.conc)
            for n, c in self.comp.all_comps().items()
        }

    def ea_vol(self, mix_vol: Optional[pint.Quantity]) -> pint.Quantity:
        return self.set_dest_vol

    def tx_vol(self, mix_vol: Optional[pint.Quantity]) -> pint.Quantity:
        return self.set_dest_vol * self.number

    def mixlines(
        self, mix_vol: pint.Quantity, include_ea: bool
    ) -> Sequence[Sequence[Union[str, pint.Quantity, int]]]:
        if include_ea:
            return [
                [
                    self.comp.name,
                    self.comp.conc,
                    self.dest_conc(mix_vol),
                    self.number,
                    self.ea_vol(mix_vol),
                    self.tx_vol(mix_vol),
                ]
            ]

        return [
            [
                self.comp.name,
                self.comp.conc,
                self.dest_conc(mix_vol),
                self.tx_vol(mix_vol),
            ]
        ]

    @property
    def number(self) -> int:
        return self.set_number

    @property
    def name(self) -> str:
        return self.comp.name


@dataclass
class MultiFixedVol(MixComp):
    comps: Sequence[BaseComponent]
    set_name: str
    set_dest_vol: pint.Quantity

    @property  # FIXME: this assumes all equal...
    def comp_conc(self):
        return self.comps[0].conc

    def all_comps(self, mix_vol: pint.Quantity) -> Mapping[str, pint.Quantity]:
        cps = {}
        for comp in self.comps:
            for n, c in comp.all_comps().items():
                cps[n] = cps.get(n, 0 * UR("nM")) + c * (
                    self.dest_conc(mix_vol) / self.comp_conc
                )
        return cps

    def dest_conc(self, mix_vol: Optional[pint.Quantity]) -> pint.Quantity:
        return (self.comp_conc * self.set_dest_vol / mix_vol).to_compact()

    def ea_vol(self, mix_vol: Optional[pint.Quantity]) -> pint.Quantity:
        return self.set_dest_vol

    def tx_vol(self, mix_vol: Optional[pint.Quantity]) -> pint.Quantity:
        return self.set_dest_vol * self.number

    def mixlines(
        self, mix_vol: pint.Quantity, include_ea: bool
    ) -> Sequence[Sequence[Union[str, pint.Quantity, int]]]:
        if include_ea:
            return [
                [
                    self.set_name,
                    self.comp_conc,
                    self.dest_conc(mix_vol),
                    self.number,
                    self.ea_vol(mix_vol),
                    self.tx_vol(mix_vol),
                ]
            ]
        else:
            return [
                [comp.name, comp.conc, self.dest_conc(mix_vol), self.ea_vol(mix_vol)]
                for comp in self.comps
            ]

    @property
    def number(self) -> int:
        return len(self.comps)

    @property
    def name(self) -> str:
        return self.set_name


@dataclass
class FixedRatio(MixComp):
    comp: BaseComponent
    source_val: float
    dest_val: float

    @property
    def number(self) -> int:
        return 1


@dataclass(frozen=True)
class Component(BaseComponent):
    set_name: str
    set_conc: pint.Quantity

    @property
    def name(self) -> str:
        return self.set_name

    @property
    def conc(self) -> pint.Quantity:
        return self.set_conc

    def all_comps(self) -> Mapping[str, pint.Quantity]:
        return {self.set_name: self.set_conc}


@dataclass
class Mix:
    name: str
    mixcomps: Sequence[MixComp]
    set_total_vol: Optional[pint.Quantity] = None
    set_conc: Union[str, pint.Quantity, None] = None
    buffer: Optional[str] = None

    @property
    def conc(self) -> pint.Quantity:
        if isinstance(self.set_conc, pint.Quantity):
            return self.set_conc
        elif isinstance(self.set_conc, str):
            for mc in self.mixcomps:
                if mc.name == self.set_conc:
                    return mc.dest_conc(self.total_volume)
            raise ValueError
        elif self.set_conc is None:
            return self.mixcomps[0].dest_conc(self.total_volume)
        else:
            raise NotImplemented

    @property
    def total_volume(self) -> pint.Quantity:
        if self.set_total_vol is not None:
            return self.set_total_vol
        else:
            return sum([c.tx_vol(None) for c in self.mixcomps], 0 * UR("µL"))

    @property
    def buffer_volume(self) -> pint.Quantity:
        mvol = sum(c.tx_vol(self.total_volume) for c in self.mixcomps)
        return self.total_volume - mvol

    def mdtable(self):
        tv = self.total_volume

        mixlines = []

        allnums1 = [mc.number == 1 for mc in self.mixcomps]
        include_ea = not all(allnums1)

        for mixcomp in self.mixcomps:
            mixlines += mixcomp.mixlines(tv, include_ea)

        if self.set_total_vol is not None:
            if include_ea:
                mixlines.append(["Buffer", "", "", "", "", self.buffer_volume])
            else:
                mixlines.append(["Buffer", "", "", self.buffer_volume])

        return tabulate(mixlines, MIXHEAD_EA if include_ea else MIXHEAD_NO_EA, "pipe")

    def all_comps(self) -> Mapping[str, pint.Quantity]:
        cps = {}
        for mcomp in self.mixcomps:
            for n, c in mcomp.all_comps(self.total_volume).items():
                cps[n] = cps.get(n, 0 * UR("nM")) + c
        return cps

    def _repr_markdown_(self):
        return f"Mix: {self.name}, Conc: {self.conc}\n\n" + self.mdtable()

    def __str__(self):
        return self.mdtable()
