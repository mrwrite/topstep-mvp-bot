import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { Contract, fetchContracts } from '../api/contracts';

type Integration = {
  id: number;
  display_name: string;
  provider: string;
  status: string;
  metadata?: Record<string, unknown>;
};

type ActiveIntegrationResponse = {
  active: Integration | null;
};

export function useActiveIntegrationContracts() {
  const [activeIntegration, setActiveIntegration] = useState<Integration | null>(null);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [contractsSource, setContractsSource] = useState<string | undefined>(undefined);
  const [contractsError, setContractsError] = useState<string | undefined>(undefined);
  const [loadingContracts, setLoadingContracts] = useState(false);
  const lastContractsIntegrationId = useRef<number | undefined>(undefined);

  const refreshActiveIntegration = useCallback(async () => {
    try {
      const res = await api.get<ActiveIntegrationResponse>('/integrations/active');
      setActiveIntegration(res.data.active ?? null);
      return res.data.active ?? null;
    } catch (err) {
      console.error('Failed to load active integration', err);
      setActiveIntegration(null);
      return null;
    }
  }, []);

  const refreshContracts = useCallback(async (integrationId?: number) => {
    setLoadingContracts(true);
    setContractsError(undefined);
    try {
      const { items, source, error } = await fetchContracts(integrationId);
      setContracts(items);
      setContractsSource(source);
      if (error) {
        setContractsError(error);
      }
      lastContractsIntegrationId.current = integrationId;
    } catch (err) {
      console.error('Failed to load contracts', err);
      setContracts([]);
      setContractsSource(undefined);
      setContractsError('Unable to load contracts.');
    } finally {
      setLoadingContracts(false);
    }
  }, []);

  const setActiveIntegrationAndLoadContracts = useCallback(
    async (integrationId: number) => {
      try {
        const res = await api.put(`/integrations/${integrationId}/activate`);
        const active = res.data?.active ?? null;
        if (active) {
          setActiveIntegration(active);
        } else {
          await refreshActiveIntegration();
        }
        localStorage.setItem('activeIntegrationId', String(integrationId));
        await refreshContracts(integrationId);
        return active;
      } catch (err) {
        console.error('Failed to activate integration', err);
        setContractsError('Unable to activate integration.');
        throw err;
      }
    },
    [refreshActiveIntegration, refreshContracts]
  );

  useEffect(() => {
    const init = async () => {
      const active = await refreshActiveIntegration();
      if (active?.id) {
        await refreshContracts(active.id);
      } else {
        await refreshContracts();
      }
    };
    init();
  }, [refreshActiveIntegration, refreshContracts]);

  useEffect(() => {
    const integrationId = activeIntegration?.id;
    if (!integrationId) return;
    if (lastContractsIntegrationId.current === integrationId) return;
    refreshContracts(integrationId);
  }, [activeIntegration?.id, refreshContracts]);

  return {
    activeIntegration,
    contracts,
    contractsError,
    contractsSource,
    loadingContracts,
    refreshActiveIntegration,
    refreshContracts,
    setActiveIntegrationAndLoadContracts,
  };
}
