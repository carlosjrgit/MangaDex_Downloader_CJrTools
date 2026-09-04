# Política de Segurança — CJ Manga Downloader

Levamos a segurança e a privacidade de nossos usuários e colaboradores muito a sério.
Este documento descreve as diretrizes para relatar vulnerabilidades e boas práticas de segurança do projeto.

---

## 1. Versões Suportadas

Apenas a versão estável mais recente mantida na branch principal (`main`) recebe correções ativas de segurança:

| Versão | Suportada |
| :--- | :--- |
| `1.0.x` (Atual) | :white_check_mark: Sim |
| `< 1.0.0` | :x: Não |

---

## 2. Como Reportar uma Vulnerabilidade

> [!IMPORTANT]
> **NÃO** abra Issues públicas nem envie mensagens em fóruns abertos para relatar vulnerabilidades, exploits ou vazamento de segredos.

Se você identificou uma potencial vulnerabilidade de segurança:

1. **GitHub Private Vulnerability Reporting (Recomendado):**
   - Acesse a aba **Security** do repositório no GitHub.
   - Clique em **Report a vulnerability** para abrir um relatório confidencial direto aos mantenedores.
2. **Contato Privado:**
   - Caso o recurso de reporte privado não esteja disponível no momento, entre em contato diretamente com o mantenedor principal através dos canais privados do perfil oficial do GitHub.

### O que incluir no seu relatório:
- Descrição clara do tipo de vulnerabilidade (ex: Path Traversal, SSRF, DoS, Injeção).
- Passos detalhados para reproduzir o problema (PoC - Proof of Concept defensivo).
- Impacto potencial da falha na máquina do usuário.
- Proposta de correção ou mitigação, caso disponível.

---

## 3. Diretrizes de Segurança do Software

- **Princípio do Menor Privilégio:** O software não requer privilégios de Administrador (`root` / `sudo`) para funcionar. Nunca execute este downloader com permissões elevadas.
- **Isolamento de Filesystem:** Todos os arquivos baixados e arquivos compactados (`.cbz`) são sanitizados contra caracteres de controle, nomes reservados do sistema operacional e ataques de Path Traversal (`..`).
- **Validação de Protocolos de Rede:** Apenas conexões remotas seguras via HTTP/HTTPS são aceitas para download de páginas e scraping. Esquemas arbitrários como `file://` são estritamente rejeitados.
- **Proteção de Segredos e Dados:** O projeto não armazena nem distribui tokens, credenciais ou dados pessoais no repositório público.
