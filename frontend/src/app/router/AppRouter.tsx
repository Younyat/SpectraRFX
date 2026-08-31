import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import { moduleRoutes } from '../modules/labModules';
import { AppLayout } from '../../presentation/views/AppLayout';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: moduleRoutes,
  },
]);

export const AppRouter = () => {
  return <RouterProvider router={router} />;
};
