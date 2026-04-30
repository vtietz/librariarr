import { useCallback, useState } from "react";
import { deleteShadowFolder } from "../api/client";
import type { MappedDirectory } from "./DirectoryMapperRows";
import type { Dispatch, SetStateAction } from "react";

type Params = {
  setLoadError: (message: string | null) => void;
  setMappedDirectories: Dispatch<SetStateAction<MappedDirectory[]>>;
  loadMappedDirectories: () => Promise<void>;
};

export function useDeleteShadowAction({
  setLoadError,
  setMappedDirectories,
  loadMappedDirectories
}: Params) {
  const [deletingPath, setDeletingPath] = useState<string | null>(null);
  const [pendingDeletePath, setPendingDeletePath] = useState<string | null>(null);

  const requestDelete = useCallback((virtualPath: string) => {
    setPendingDeletePath(virtualPath);
  }, []);

  const cancelDelete = useCallback(() => {
    setPendingDeletePath(null);
  }, []);

  const confirmDelete = useCallback(async () => {
    if (!pendingDeletePath) return;
    const pathToDelete = pendingDeletePath;
    setPendingDeletePath(null);
    setDeletingPath(pathToDelete);
    setLoadError(null);
    try {
      await deleteShadowFolder(pathToDelete);
      setMappedDirectories((previous) =>
        previous.filter((entry) => entry.virtual_path !== pathToDelete)
      );
      await loadMappedDirectories();
    } catch (error) {
      setLoadError(
        error instanceof Error
          ? `Failed to remove shadow folder: ${error.message}`
          : "Failed to remove shadow folder."
      );
    } finally {
      setDeletingPath(null);
    }
  }, [pendingDeletePath, setLoadError, setMappedDirectories, loadMappedDirectories]);

  return { deletingPath, pendingDeletePath, requestDelete, cancelDelete, confirmDelete };
}
