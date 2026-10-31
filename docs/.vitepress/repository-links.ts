import { existsSync, statSync } from 'node:fs'
import { dirname, isAbsolute, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const docsRoot = fileURLToPath(new URL('../', import.meta.url))
const repoRoot = resolve(docsRoot, '..')
const repository = 'https://github.com/RUC-NLPIR/FlashRSI'

// Existing Markdown remains readable on GitHub. On the website, links to
// source/config files go to the repository; links to docs stay on the site.
export function repositoryLinks(md: any) {
  md.core.ruler.after('inline', 'flashrsi-repository-links', (state: any) => {
    const source = state.env.relativePath || 'index.md'
    const rewrite = (href: string) => {
      if (!href || /^(?:[a-z][a-z\d+.-]*:|\/|#)/i.test(href)) return href
      const [, pathname, suffix = ''] = href.match(/^([^?#]+)(.*)$/) || []
      if (!pathname) return href
      const target = resolve(docsRoot, dirname(source), decodeURIComponent(pathname))
      const inDocs = relative(docsRoot, target)
      if (!inDocs.startsWith(`..${sep}`) && !isAbsolute(inDocs) && target.endsWith('.md')) {
        const route = inDocs === 'README.md' ? 'overview.md' : inDocs.split(sep).join('/')
        return `/${route}${suffix}`
      }
      const inRepo = relative(repoRoot, target).split(sep).join('/')
      if (inRepo.startsWith('../') || !existsSync(target)) return href
      const kind = statSync(target).isDirectory() ? 'tree' : 'blob'
      return `${repository}/${kind}/main/${inRepo}${suffix}`
    }
    const walk = (tokens: any[]) => {
      for (const token of tokens) {
        if (token.type === 'link_open') {
          const href = token.attrGet('href')
          if (href) token.attrSet('href', rewrite(href))
        }
        if (token.children) walk(token.children)
      }
    }
    walk(state.tokens)
  })
}
