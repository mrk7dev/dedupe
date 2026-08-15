from __future__ import annotations


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


class _Node:
    __slots__ = ("file_id", "value", "children")

    def __init__(self, file_id: int, value: int):
        self.file_id = file_id
        self.value = value
        self.children: dict[int, "_Node"] = {}


class BKTree:
    """Hamming-distance BK-tree over integer hashes (e.g. 64-bit pHashes).

    Gives ~O(log n) near-neighbor lookups instead of the O(n^2) pairwise
    comparison a naive "compare every image to every other image" approach
    would need — the difference that matters once a photo library gets into
    the hundreds of thousands of files.
    """

    def __init__(self) -> None:
        self._root: _Node | None = None

    def add(self, file_id: int, value: int) -> None:
        if self._root is None:
            self._root = _Node(file_id, value)
            return
        node = self._root
        while True:
            dist = hamming(value, node.value)
            child = node.children.get(dist)
            if child is None:
                node.children[dist] = _Node(file_id, value)
                return
            node = child

    def query(self, value: int, threshold: int) -> list[tuple[int, int]]:
        """Return [(file_id, distance), ...] for all entries within threshold."""
        if self._root is None:
            return []
        results: list[tuple[int, int]] = []
        stack = [self._root]
        while stack:
            node = stack.pop()
            dist = hamming(value, node.value)
            if dist <= threshold:
                results.append((node.file_id, dist))
            lo, hi = dist - threshold, dist + threshold
            for child_dist, child in node.children.items():
                if lo <= child_dist <= hi:
                    stack.append(child)
        return results
