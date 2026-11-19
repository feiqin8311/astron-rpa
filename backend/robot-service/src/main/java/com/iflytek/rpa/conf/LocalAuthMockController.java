package com.iflytek.rpa.conf;

import com.iflytek.rpa.common.feign.entity.Tenant;
import com.iflytek.rpa.common.feign.entity.TenantExpirationDto;
import com.iflytek.rpa.common.feign.entity.User;
import com.iflytek.rpa.common.feign.entity.dto.RoleBaseDto;
import com.iflytek.rpa.common.feign.entity.dto.TenantInfoDto;
import com.iflytek.rpa.common.feign.entity.dto.UserExtendDto;
import com.iflytek.rpa.utils.response.AppResponse;
import java.util.Collections;
import java.util.List;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 单机离线模式下的本地身份与会话 Mock 控制器。
 * 当配置 auth.enabled=false 时激活，接管 RpaAuthFeign 的用户与会话查询，
 * 为后端提供稳定的本地管理员上下文，避免依赖独立的 rpa-auth 与 Casdoor 容器。
 */
@RestController
@RequestMapping("/api/rpa-auth")
@ConditionalOnProperty(name = "auth.enabled", havingValue = "false")
public class LocalAuthMockController {

    private User createLocalUser() {
        User user = new User();
        user.setId("local-user");
        user.setName("本地用户");
        user.setLoginName("admin");
        user.setOrgId("default");
        user.setOrgName("默认组织");
        user.setStatus(1);
        return user;
    }

    private Tenant createLocalTenant() {
        Tenant tenant = new Tenant();
        tenant.setId("default");
        tenant.setName("默认空间");
        tenant.setTenantCode("default");
        tenant.setStatus(1);
        return tenant;
    }

    @GetMapping("/user/info")
    public AppResponse<User> getLoginUser() {
        return AppResponse.success(createLocalUser());
    }

    @PostMapping("/user/getUserExtendInfo")
    public AppResponse<UserExtendDto> getUserExtendInfo(
            @RequestParam(value = "tenantId", required = false) String tenantId) {
        UserExtendDto dto = new UserExtendDto();
        dto.setUser(createLocalUser());
        RoleBaseDto adminRole = new RoleBaseDto();
        adminRole.setId("admin");
        adminRole.setName("管理员");
        dto.setRoles(Collections.singletonList(adminRole));
        return AppResponse.success(dto);
    }

    @GetMapping("/check-session")
    public AppResponse<String> checkSession() {
        return AppResponse.success("ok");
    }

    @GetMapping("/user/queryAllListByOrgId")
    public AppResponse<List<User>> queryAllListByOrgId(
            @RequestParam(value = "orgId", required = false) String orgId) {
        return AppResponse.success(Collections.singletonList(createLocalUser()));
    }

    @GetMapping("/tenant/getTenantId")
    public AppResponse<String> getTenantId() {
        return AppResponse.success("default");
    }

    @GetMapping("/tenant/current/id")
    public AppResponse<String> getCurrentTenantId() {
        return AppResponse.success("default");
    }

    @GetMapping("/tenant/current/name")
    public AppResponse<String> getCurrentTenantName() {
        return AppResponse.success("默认空间");
    }

    @GetMapping("/user/getNameById")
    public AppResponse<String> getNameById(@RequestParam(value = "id", required = false) String id) {
        return AppResponse.success("本地用户");
    }

    @GetMapping("/tenant/info")
    public AppResponse<Tenant> queryTenantInfoById(
            @RequestParam(value = "tenantId", required = false) String tenantId) {
        return AppResponse.success(createLocalTenant());
    }

    @GetMapping("/tenant/getTenantInfo")
    public AppResponse<TenantInfoDto> getTenantInfo() {
        TenantInfoDto dto = new TenantInfoDto();
        dto.setId("default");
        dto.setName("默认空间");
        dto.setCode("default");
        dto.setManagerId("local-user");
        dto.setManagerName("本地用户");
        return AppResponse.success(dto);
    }

    @GetMapping("/tenant/list")
    public AppResponse<List<Tenant>> getTenantList(
            @RequestParam(value = "tempToken", required = false) String tempToken) {
        return AppResponse.success(Collections.singletonList(createLocalTenant()));
    }

    @GetMapping("/tenant/getTenantUserType")
    public AppResponse<Integer> getTenantUserType(
            @RequestParam(value = "userId", required = false) String userId,
            @RequestParam(value = "tenantId", required = false) String tenantId) {
        return AppResponse.success(1);
    }

    @GetMapping("/tenant/expiration")
    public AppResponse<TenantExpirationDto> getExpiration() {
        TenantExpirationDto dto = new TenantExpirationDto();
        dto.setTenantId("default");
        dto.setIsExpired(false);
        dto.setShouldAlert(false);
        return AppResponse.success(dto);
    }
}
