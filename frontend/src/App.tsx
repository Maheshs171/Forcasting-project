import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Layout from "./components/Layout";
import Overview from "./pages/Overview";
import MetricDashboard from "./pages/MetricDashboard";
import Operations from "./pages/Operations";
import Settings from "./pages/Settings";
import DataExplorer from "./pages/DataExplorer";
import AzureOps from "./pages/AzureOps";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: 1,
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Overview />} />
            <Route path="forecast/:metric" element={<MetricDashboard />} />
            <Route path="train" element={<Operations />} />
            <Route path="explore" element={<DataExplorer />} />
            <Route path="azure" element={<AzureOps />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
