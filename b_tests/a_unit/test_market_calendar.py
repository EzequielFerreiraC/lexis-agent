from datetime import date

import pytest

from lexis.a_domain import market_calendar as cal
from lexis.a_domain.models import TipoEvento
from lexis.d_validation import coherence as rules


@pytest.mark.parametrize("ano,esperada", [
    (2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)), (2026, date(2026, 4, 5)), (2027, date(2027, 3, 28)),
])
def test_pascoa(ano, esperada):
    assert cal.pascoa(ano) == esperada


def test_feriados_moveis_de_2026():
    f = cal.feriados(2026)
    # Carnaval 16-17/02, Sexta-feira Santa 03/04, Corpus Christi 04/06
    assert {date(2026, 2, 16), date(2026, 2, 17), date(2026, 4, 3), date(2026, 6, 4)} <= f


def test_feriados_fixos_incluem_vesperas_sem_pregao():
    f = cal.feriados(2026)
    assert {date(2026, 1, 1), date(2026, 4, 21), date(2026, 11, 20), date(2026, 12, 24), date(2026, 12, 31)} <= f


def test_proximo_dia_util_pula_fim_de_semana_e_feriado():
    assert cal.proximo_dia_util(date(2026, 6, 12)) == date(2026, 6, 15)  # sexta -> segunda
    assert cal.proximo_dia_util(date(2026, 6, 3)) == date(2026, 6, 5)  # quarta -> sexta (quinta é Corpus Christi)
    assert cal.proximo_dia_util(date(2026, 4, 2)) == date(2026, 4, 6)  # quinta -> segunda (Sexta-feira Santa)
    assert cal.proximo_dia_util(date(2026, 12, 30)) == date(2027, 1, 4)  # 31/12 e 01/01 + fim de semana


def test_fora_dos_anos_cobertos_so_considera_fim_de_semana():
    assert not cal.coberto(date(2023, 11, 20))
    assert cal.eh_dia_util(date(2023, 11, 20))  # feriado só a partir de 2024: não afirma o que não conferiu


def test_ex_apos_feriado_e_aceito():
    d = {"data_com": date(2026, 6, 3), "data_ex": date(2026, 6, 5)}  # Corpus Christi no meio
    r = next(x for x in rules.checar_datas(TipoEvento.DIVIDENDO, d) if x.id == "DATAS_EX_NAO_E_DIA_UTIL_SEGUINTE")
    assert r.resultado == "OK"


def test_ex_em_feriado_e_aviso():
    d = {"data_com": date(2026, 6, 3), "data_ex": date(2026, 6, 4)}  # ex em Corpus Christi
    r = next(x for x in rules.checar_datas(TipoEvento.DIVIDENDO, d) if x.id == "DATAS_EX_NAO_E_DIA_UTIL_SEGUINTE")
    assert r.resultado == "FALHA" and r.severidade.value == "AVISO"
    assert r.esperado == "data_ex=2026-06-05"
    assert "calendário de feriados da B3" in r.detalhe


def test_ex_fora_dos_anos_cobertos_avisa_que_so_usou_fim_de_semana():
    d = {"data_com": date(2023, 11, 17), "data_ex": date(2023, 11, 20)}
    r = next(x for x in rules.checar_datas(TipoEvento.DIVIDENDO, d) if x.id == "DATAS_EX_NAO_E_DIA_UTIL_SEGUINTE")
    assert r.resultado == "OK" and "só considera sábados e domingos" in r.detalhe
