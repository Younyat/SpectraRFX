import { useCallback } from 'react';
import {
  useAppActions,
  useCurrentRecording,
  useCurrentSession,
  useRecordings,
  useSessions,
} from '../../app/store/AppStore';
import { ApiService } from '../../app/services/ApiService';
import { Recording } from '../../shared/types';

const apiService = new ApiService();

export const useRecordingController = () => {
  const actions = useAppActions();
  const recordings = useRecordings();
  const sessions = useSessions();
  const currentRecording = useCurrentRecording();
  const currentSession = useCurrentSession();

  const startRecording = useCallback(async (type: 'iq' | 'audio', duration?: number): Promise<Recording> => {
    const recording = await apiService.startRecording(type, duration);
    actions.setCurrentRecording(recording);
    actions.addRecording(recording);
    return recording;
  }, [actions]);

  const stopRecording = useCallback(async (): Promise<void> => {
    await apiService.stopRecording();
    actions.setCurrentRecording(null);
  }, [actions]);

  const loadRecordings = useCallback(async (): Promise<Recording[]> => {
    const loadedRecordings = await apiService.getRecordings();
    loadedRecordings.forEach((recording) => actions.addRecording(recording));
    return loadedRecordings;
  }, [actions]);

  const createSession = useCallback(async (name: string) => {
    const session = await apiService.createSession(name);
    actions.addSession(session);
    actions.setCurrentSession(session);
    return session;
  }, [actions]);

  const setCurrentSession = useCallback((sessionId: string | null) => {
    if (sessionId === null) {
      actions.setCurrentSession(null);
      return;
    }

    const session = sessions.find((item) => item.id === sessionId);
    if (session) {
      actions.setCurrentSession(session);
    }
  }, [actions, sessions]);

  return {
    startRecording,
    stopRecording,
    loadRecordings,
    getRecordingsBySession: useCallback((sessionId: string) => (
      recordings.filter((recording) => recording.sessionId === sessionId || !recording.sessionId)
    ), [recordings]),
    getCurrentRecording: useCallback(() => currentRecording, [currentRecording]),
    isRecording: useCallback(() => currentRecording !== null, [currentRecording]),
    createSession,
    setCurrentSession,
    getSessions: useCallback(() => sessions, [sessions]),
    getCurrentSession: useCallback(() => currentSession, [currentSession]),
  };
};
