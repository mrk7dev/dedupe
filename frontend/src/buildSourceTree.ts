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

/**
 * Rebuilds the source side of a comparison run as a folder tree, so gaps can
 * be browsed spatially instead of only as a flat list. Folders with nothing
 * left under them (e.g. every file in that folder matched, and missingOnly
 * is on) are dropped automatically — they're just never created below.
 */
export function buildSourceTree(files: CompareFile[], sourceRoot: string, missingOnly: boolean): TreeNode[] {
  const root = emptyDir(sourceRoot)
  const relevant = files.filter((f) => f.category !== 'target_only' && (!missingOnly || f.category === 'source_only'))

  for (const file of relevant) {
    const rel = file.dir.startsWith(sourceRoot) ? file.dir.slice(sourceRoot.length) : file.dir
    const parts = rel.split('/').filter(Boolean)

    let cursor = root
    let pathAcc = sourceRoot
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

  return toNodes(root)
}
