import type { CompareFile, TreeNode } from './types'

interface DirAccumulator {
  path: string
  dirs: Map<string, DirAccumulator>
  files: TreeNode[]
}

function emptyDir(path: string): DirAccumulator {
  return { path, dirs: new Map(), files: [] }
}

function toNodes(acc: DirAccumulator): TreeNode[] {
  const dirNodes = [...acc.dirs.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([name, child]) => ({ id: child.path, name, children: toNodes(child) }))
  const fileNodes = [...acc.files].sort((a, b) => a.name.localeCompare(b.name))
  return [...dirNodes, ...fileNodes]
}

// True when `dir` is `root` itself or a path nested under it (not merely a
// string-prefix match — avoids "/volume1/foo" matching "/volume1/foobar").
function isUnderRoot(dir: string, root: string): boolean {
  return dir === root || dir.startsWith(`${root}/`)
}

function buildTreeForRoot(files: CompareFile[], root: string, missingOnly: boolean): TreeNode[] {
  const rootAcc = emptyDir(root)
  const relevant = files.filter(
    (f) => isUnderRoot(f.dir, root) && f.category !== 'target_only' && (!missingOnly || f.category === 'source_only'),
  )

  for (const file of relevant) {
    const rel = file.dir.slice(root.length)
    const parts = rel.split('/').filter(Boolean)

    let cursor = rootAcc
    let pathAcc = root
    for (const part of parts) {
      pathAcc += `/${part}`
      let child = cursor.dirs.get(part)
      if (!child) {
        child = emptyDir(pathAcc)
        cursor.dirs.set(part, child)
      }
      cursor = child
    }

    cursor.files.push({ id: file.id, name: file.name, isFile: true, category: file.category })
  }

  return toNodes(rootAcc)
}

/**
 * Rebuilds the source side of a comparison run as a folder tree, so gaps can
 * be browsed spatially instead of only as a flat list. Folders with nothing
 * left under them (e.g. every file in that folder matched, and missingOnly
 * is on) are dropped automatically — they're just never created below.
 *
 * Returns a forest: one top-level node per selected source root, each
 * containing that root's own tree. Roots are assumed non-overlapping
 * (enforced server-side at /compare/start), so a file's owning root is
 * found unambiguously by prefix match.
 */
export function buildSourceTree(files: CompareFile[], sourceRoots: string[], missingOnly: boolean): TreeNode[] {
  return sourceRoots
    .map((root) => ({
      id: root,
      name: root.split('/').filter(Boolean).pop() ?? root,
      children: buildTreeForRoot(files, root, missingOnly),
    }))
    .filter((node) => node.children.length > 0)
}
