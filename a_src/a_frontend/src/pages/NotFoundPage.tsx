import { Link } from 'react-router-dom';
import { Icone } from '../components/Icon';
import { useTituloDaPagina } from '../components/Layout';

export function NaoEncontrada() {
  useTituloDaPagina('Página não encontrada');
  return (
    <div className="vazio vazio--pagina">
      <Icone nome="busca" tamanho={32} />
      <h1>Página não encontrada</h1>
      <p>
        O endereço não existe neste console. <Link to="/">Voltar para Executar</Link>.
      </p>
    </div>
  );
}
