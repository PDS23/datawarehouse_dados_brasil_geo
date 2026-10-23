"""Interrupção limpa: `docker stop` envia SIGTERM; sem tratamento o Python morre na hora e a execução
fica "rodando" para sempre em catalogo.cargas. Com este tratamento a interrupção vira uma exceção, o
contexto Carga fecha o registro (status 'falhou', mensagem 'Interrompido') e a transação pendente é desfeita.
Cada unidade de trabalho (ex.: uma cultura x ano) já é confirmada sozinha, então nada fica pela metade."""
import signal


class Interrompido(KeyboardInterrupt):
    pass


def tratar_sigterm():
    def _h(_signum, _frame):
        raise Interrompido("interrompido por SIGTERM (docker stop)")
    signal.signal(signal.SIGTERM, _h)
