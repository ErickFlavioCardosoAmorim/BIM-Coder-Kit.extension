# -*- coding: utf-8 -*-
__title__ = "Exportar quadros"
__doc__ = "Seleciona quadros eletricos e exporta todas as celulas para Excel."

import System
import re
from System.Reflection import BindingFlags
from System.Runtime.InteropServices import Marshal

from Autodesk.Revit.DB import FilteredElementCollector
from Autodesk.Revit.DB import SectionType
from Autodesk.Revit.DB.Electrical import PanelScheduleView
from pyrevit import forms, revit, script

try:
    texto_tipo = type(u"")
except Exception:
    texto_tipo = str


def texto(valor):
    """Converte valores .NET e valores vazios para texto exportavel."""
    if valor is None:
        return ""
    try:
        return texto_tipo(valor)
    except Exception:
        return str(valor)


def nome_secao(secao):
    nomes = {
        SectionType.Header: "Header",
        SectionType.Body: "Body",
        SectionType.Footer: "Footer"
    }
    return nomes.get(secao, texto(secao))


def id_inteiro(elemento):
    """Suporta ElementId.IntegerValue e ElementId.Value entre versoes do Revit."""
    identificador = elemento.Id
    try:
        return identificador.IntegerValue
    except AttributeError:
        return identificador.Value


def rotulo_quadro(quadro):
    return "{} [ID {}]".format(texto(quadro.Name), texto(id_inteiro(quadro)))


def com_propriedade(objeto, nome, argumentos=None):
    return objeto.GetType().InvokeMember(
        nome,
        BindingFlags.GetProperty,
        None,
        objeto,
        argumentos
    )


def com_metodo(objeto, nome, argumentos=None):
    return objeto.GetType().InvokeMember(
        nome,
        BindingFlags.InvokeMethod,
        None,
        objeto,
        argumentos
    )


def com_definir_propriedade(objeto, nome, valor):
    objeto.GetType().InvokeMember(
        nome,
        BindingFlags.SetProperty,
        None,
        objeto,
        (valor,)
    )


def texto_celula(quadro, secao_data, secao, linha, coluna):
    """Usa o texto formatado do PanelScheduleView antes do fallback da grade."""
    try:
        valor = quadro.GetCellText(secao, linha, coluna)
        if valor is not None and texto(valor).strip():
            return texto(valor).strip()
    except Exception:
        pass
    try:
        return texto(secao_data.GetCellText(linha, coluna)).strip()
    except Exception:
        return ""


def coletar_tabela(quadro):
    """Le a grade completa do quadro, preservando linhas e colunas vazias."""
    secoes_lidas = []
    tabela = quadro.GetTableData()
    secoes = (SectionType.Header, SectionType.Body, SectionType.Footer)

    for secao in secoes:
        try:
            secao_data = tabela.GetSectionData(secao)
            if not secao_data:
                continue
            primeira_linha = secao_data.FirstRowNumber
            primeira_coluna = secao_data.FirstColumnNumber
            ultima_linha = primeira_linha + secao_data.NumberOfRows
            ultima_coluna = primeira_coluna + secao_data.NumberOfColumns
            grade = []
            for linha in range(primeira_linha, ultima_linha):
                valores_linha = []
                for coluna in range(primeira_coluna, ultima_coluna):
                    valor = texto_celula(quadro, secao_data, secao, linha, coluna)
                    valores_linha.append(valor)
                grade.append(valores_linha)
            secoes_lidas.append((nome_secao(secao), grade))
        except Exception as erro:
            secoes_lidas.append((nome_secao(secao), [["ERRO AO LER SECAO: {}".format(texto(erro))]]))
    return secoes_lidas


def nome_planilha(nome, usados):
    nome = re.sub(r"[\\/*?:\[\]]", "_", nome).strip() or "Quadro"
    nome = nome[:31]
    original = nome
    numero = 2
    while nome.lower() in usados:
        sufixo = " ({})".format(numero)
        nome = original[:31 - len(sufixo)] + sufixo
        numero += 1
    usados.add(nome.lower())
    return nome


def exportar_excel(caminho, quadros_tabelas):
    """Cria um arquivo XLSX usando a instalacao local do Microsoft Excel."""
    tipo_excel = System.Type.GetTypeFromProgID("Excel.Application")
    if tipo_excel is None:
        raise Exception("Microsoft Excel nao foi encontrado neste computador.")

    excel = System.Activator.CreateInstance(tipo_excel)
    pasta_trabalho = None
    planilhas = []
    try:
        workbooks = com_propriedade(excel, "Workbooks")
        pasta_trabalho = com_metodo(workbooks, "Add")
        worksheets = com_propriedade(pasta_trabalho, "Worksheets")
        usados = set()
        for indice, item in enumerate(quadros_tabelas):
            quadro, secoes = item
            if indice == 0:
                planilha = com_propriedade(worksheets, "Item", (1,))
            else:
                planilha = com_metodo(worksheets, "Add")
            planilhas.append(planilha)
            com_definir_propriedade(planilha, "Name", nome_planilha(texto(quadro.Name), usados))

            linha_excel = 1
            for nome, grade in secoes:
                for linha in grade:
                    for coluna, valor in enumerate(linha, 1):
                        celula = com_propriedade(planilha, "Cells", (linha_excel, coluna))
                        com_definir_propriedade(celula, "Value2", valor)
                    linha_excel += 1
                linha_excel += 1

        try:
            com_metodo(pasta_trabalho, "SaveAs", (caminho, 51))
        except Exception as erro:
            raise Exception(
                "O Excel nao conseguiu salvar em '{}'. "
                "Verifique se o arquivo esta fechado e se a pasta permite gravacao. "
                "Detalhe: {}".format(caminho, texto(erro))
            )
        com_metodo(pasta_trabalho, "Close", (True,))
    finally:
        if pasta_trabalho is not None:
            try:
                com_metodo(pasta_trabalho, "Close", (False,))
            except Exception:
                pass
        if excel is not None:
            try:
                # O IronPython pode expor o Excel como __ComObject sem membros dinamicos.
                excel.GetType().InvokeMember(
                    "Quit",
                    BindingFlags.InvokeMethod,
                    None,
                    excel,
                    None
                )
            except Exception:
                pass
        for objeto in planilhas + [pasta_trabalho, excel]:
            if objeto is not None:
                try:
                    Marshal.ReleaseComObject(objeto)
                except Exception:
                    pass


def run_script():
    doc = revit.doc
    quadros = list(
        FilteredElementCollector(doc)
        .OfClass(PanelScheduleView)
        .ToElements()
    )
    quadros.sort(key=lambda quadro: texto(quadro.Name).lower())

    if not quadros:
        forms.alert("Nenhum quadro eletrico foi encontrado no projeto.", title="Exportar quadros")
        return

    opcoes = [rotulo_quadro(quadro) for quadro in quadros]
    selecionados = forms.SelectFromList.show(
        opcoes,
        title="Selecione os quadros para exportar",
        button_name="Exportar selecionados",
        multiselect=True
    )
    if not selecionados:
        return

    por_rotulo = dict((rotulo_quadro(quadro), quadro) for quadro in quadros)
    quadros_tabelas = []
    for rotulo in selecionados:
        quadro = por_rotulo[rotulo]
        quadros_tabelas.append((quadro, coletar_tabela(quadro)))

    if not quadros_tabelas:
        forms.alert("Os quadros selecionados nao possuem celulas preenchidas.", title="Exportar quadros")
        return

    caminho = forms.save_file(
        title="Salvar dados dos quadros para o Excel",
        default_name="dados_quadros_eletricos.xlsx",
        files_filter="Arquivo Excel (*.xlsx)|*.xlsx"
    )
    if not caminho:
        return

    try:
        exportar_excel(caminho, quadros_tabelas)
    except Exception as erro:
        forms.alert(
            "Nao foi possivel criar o arquivo Excel.\n\n{}\n\n"
            "Tente salvar em Documentos ou na Area de Trabalho e feche "
            "qualquer arquivo com o mesmo nome.".format(texto(erro)),
            title="Erro na exportacao"
        )
        return
    output = script.get_output()
    output.print_md("**Exportacao concluida:** {}".format(caminho))
    output.print_md("**Quadros selecionados:** {} | **Abas criadas:** {}".format(
        len(selecionados), len(quadros_tabelas)
    ))
    forms.alert(
        "Exportacao concluida no arquivo Excel.\n\n{}".format(caminho),
        title="Exportar quadros"
    )


if __name__ == "__main__":
    run_script()