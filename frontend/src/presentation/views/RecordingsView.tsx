import React, { useState, useEffect } from 'react';
import { Play, Square, Download, FolderOpen } from 'lucide-react';
import { useRecordingController } from '../controllers/RecordingController';
import { useSessions, useCurrentSession } from '../../app/store/AppStore';
import { formatDuration, formatFileSize } from '../../shared/utils';
import { cn } from '../../shared/utils';

export const RecordingsView: React.FC = () => {
  const sessions = useSessions();
  const currentSession = useCurrentSession();
  const recordingController = useRecordingController();
  const loadRecordings = recordingController.loadRecordings;

  const [isRecording, setIsRecording] = useState(false);
  const [recordingType, setRecordingType] = useState<'iq' | 'audio'>('iq');
  const [newSessionName, setNewSessionName] = useState('');

  useEffect(() => {
    loadRecordings();
  }, [loadRecordings]);

  const handleStartRecording = async () => {
    try {
      await recordingController.startRecording(recordingType);
      setIsRecording(true);
    } catch (error) {
      console.error('Failed to start recording:', error);
    }
  };

  const handleStopRecording = async () => {
    try {
      await recordingController.stopRecording();
      setIsRecording(false);
    } catch (error) {
      console.error('Failed to stop recording:', error);
    }
  };

  const handleCreateSession = async () => {
    if (!newSessionName.trim()) return;

    try {
      await recordingController.createSession(newSessionName);
      setNewSessionName('');
    } catch (error) {
      console.error('Failed to create session:', error);
    }
  };

  const currentRecording = recordingController.getCurrentRecording();

  return (
    <div className="h-full flex flex-col">
      {/* Controls */}
      <div className="bg-white border-b border-gray-200 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <select
              value={recordingType}
              onChange={(e) => setRecordingType(e.target.value as 'iq' | 'audio')}
              className="px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="iq">IQ Data</option>
              <option value="audio">Audio</option>
            </select>

            <button
              onClick={isRecording ? handleStopRecording : handleStartRecording}
              className={cn(
                "flex items-center px-4 py-2 rounded-md font-medium",
                isRecording
                  ? "bg-red-600 text-white hover:bg-red-700"
                  : "bg-green-600 text-white hover:bg-green-700"
            )}
          >
              {isRecording ? <Square className="w-4 h-4 mr-2" /> : <Play className="w-4 h-4 mr-2" />}
              {isRecording ? 'Stop Recording' : 'Start Recording'}
            </button>
          </div>

          <div className="flex items-center space-x-4">
            <input
              type="text"
              placeholder="New session name"
              value={newSessionName}
              onChange={(e) => setNewSessionName(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              onClick={handleCreateSession}
              className="flex items-center px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
            >
              <FolderOpen className="w-4 h-4 mr-2" />
              New Session
            </button>
          </div>
        </div>
      </div>

      {/* Current Recording Status */}
      {currentRecording && (
        <div className="bg-yellow-50 border-l-4 border-yellow-400 p-4">
          <div className="flex items-center">
            <div className="flex-shrink-0">
              <Play className="w-5 h-5 text-yellow-400" />
            </div>
            <div className="ml-3">
              <p className="text-sm text-yellow-700">
                Recording in progress: {currentRecording.type.toUpperCase()} - {formatDuration(currentRecording.duration)}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Sessions and Recordings */}
      <div className="flex-1 overflow-auto">
        <div className="p-4 space-y-6">
          {/* Sessions */}
          <div>
            <h3 className="text-lg font-medium text-gray-900 mb-4">Sessions</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {sessions.map((session) => (
                <div
                  key={session.id}
                  className={cn(
                    "bg-white border rounded-lg p-4 cursor-pointer transition-colors",
                    currentSession?.id === session.id
                      ? "border-blue-500 bg-blue-50"
                      : "border-gray-200 hover:border-gray-300"
                  )}
                  onClick={() => recordingController.setCurrentSession(session.id)}
                >
                  <h4 className="font-medium text-gray-900">{session.name}</h4>
                  <p className="text-sm text-gray-600">
                    {new Date(session.createdAt).toLocaleDateString()}
                  </p>
                  <p className="text-sm text-gray-500">
                    {recordingController.getRecordingsBySession(session.id).length} recordings
                  </p>
                </div>
              ))}
            </div>
          </div>

          {/* Recordings */}
          {currentSession && (
            <div>
              <h3 className="text-lg font-medium text-gray-900 mb-4">
                Recordings in "{currentSession.name}"
              </h3>
              <div className="space-y-2">
                {recordingController.getRecordingsBySession(currentSession.id).map((recording) => (
                  <div key={recording.id} className="bg-white border border-gray-200 rounded-lg p-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <h4 className="font-medium text-gray-900">
                          {recording.type.toUpperCase()} Recording
                        </h4>
                        <p className="text-sm text-gray-600">
                          {new Date(recording.timestamp).toLocaleString()} - {formatDuration(recording.duration)}
                        </p>
                        <p className="text-sm text-gray-500">
                          {formatFileSize(recording.size)} - {recording.filePath}
                        </p>
                      </div>
                      <button className="flex items-center px-3 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700">
                        <Download className="w-4 h-4 mr-2" />
                        Download
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
