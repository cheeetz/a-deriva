# a-deriva — página pública e manifesto de versão

Repositório **público** com duas coisas, e nada além:

- `versao.json` — qual é a versão mais recente do jogo. O jogo consulta este arquivo quando
  abre (e a cada 6 h) pra avisar quem está com uma build velha.
- `index.html` — a página que a pessoa vê se abrir o endereço no navegador.

**O código do jogo não está aqui** e não deve vir pra cá. Este repositório é público só porque
o manifesto precisa ser lido de fora; o jogo continua no repositório privado.

## Como publicar uma versão nova

O `ferramentas/empacota.ps1` (no repositório do jogo) já gera o manifesto pronto, em
`build/versao.json`, com a mesma marca que ele carimbou no executável. Então:

```
copy "…\aderivagame\build\versao.json" .
git add versao.json
git commit -m "v0.1.0.NN"
git push
```

Em um ou dois minutos o GitHub Pages serve o arquivo novo, e os jogos que estiverem abertos
avisam na consulta seguinte.

**Confira a `conta` antes de subir.** É ela que decide — o jogo compara esse inteiro com o
dele e ignora o resto. Ela é a contagem de commits do repositório do jogo: só cresce, nunca
repete. Se ela vier menor que a que já está publicada, ninguém recebe aviso nenhum.

O campo `url` aponta pra esta mesma página, e não pro arquivo: o zip muda de lugar a cada
build, a página não.

## Como ligar o Pages (uma vez só)

Em **Settings → Pages**, escolher branch `main` e pasta `/ (root)`. O endereço fica
`https://cheeetz.github.io/a-deriva/`.

O arquivo `.nojekyll` está aqui pra impedir que o GitHub processe a pasta como um site Jekyll —
sem ele, arquivo começando com `_` seria ignorado.
