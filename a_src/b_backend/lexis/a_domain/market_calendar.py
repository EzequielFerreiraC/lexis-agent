"""Calendário de dias úteis da B3. Funções puras, sem I/O e sem dados externos.

Os feriados fixos são constantes e os móveis (Carnaval, Sexta-feira Santa, Corpus Christi) saem da Páscoa, então não há
arquivo de calendário para manter. O calendário só vale para `ANOS_COBERTOS`; fora dele `eh_dia_util` considera apenas
fins de semana e `coberto` devolve False, para o chamador dizer isso em vez de afirmar um calendário que não conferiu.
"""

from __future__ import annotations

from datetime import date, timedelta

ANOS_COBERTOS = range(2024, 2031)  # 20/11 virou feriado nacional em 2024; antes disso o calendário era outro

# (mês, dia): confraternização, Tiradentes, trabalho, independência, N. Sra. Aparecida, finados, república,
# consciência negra, vésperas de Natal e Ano Novo (sem pregão na B3) e Natal
_FIXOS = frozenset({(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (11, 20), (12, 24), (12, 25), (12, 31)})


def pascoa(ano: int) -> date:
    """Domingo de Páscoa (algoritmo gregoriano anônimo de Meeus/Jones/Butcher)."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    el = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * el) // 451
    mes, dia = divmod(h + el - 7 * m + 114, 31)
    return date(ano, mes, dia + 1)


def feriados(ano: int) -> frozenset[date]:
    """Dias em que a B3 não opera por feriado (fixos + Carnaval, Sexta-feira Santa e Corpus Christi)."""
    p = pascoa(ano)
    moveis = {p - timedelta(days=48), p - timedelta(days=47), p - timedelta(days=2), p + timedelta(days=60)}
    fixos = {date(ano, m, d) for m, d in _FIXOS}
    return frozenset(fixos | moveis)


def coberto(d: date) -> bool:
    return d.year in ANOS_COBERTOS


def eh_dia_util(d: date) -> bool:
    return d.weekday() < 5 and not (coberto(d) and d in feriados(d.year))


def proximo_dia_util(d: date) -> date:
    n = d + timedelta(days=1)
    while not eh_dia_util(n):
        n += timedelta(days=1)
    return n
